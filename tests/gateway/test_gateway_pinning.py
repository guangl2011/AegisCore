"""Gateway artifact-pinning suite: unpinned and mismatched artifacts refused.

Each negative test proves the gateway never exposes a physicalai serving
surface for an artifact it cannot vouch for: unpinned, wrong digest, wrong
revision, or malformed reference. Positive tests pin the happy path — a
pinned artifact plus an authenticated client yields a lease-bound surface.
"""

import pytest

from aegiscore.core.model import TaskCommand
from aegiscore.gateway import (
    ArtifactDescriptor,
    ArtifactHashMismatchError,
    ArtifactKind,
    ArtifactPinStore,
    ArtifactReferenceError,
    AuthenticationError,
    Certificate,
    CommandEnvelope,
    NonceError,
    ServingSurfaceKind,
    TrustStore,
    UnpinnedArtifactError,
    ZeroTrustGateway,
    sha256_hex,
)

NOW_US = 1_000_000_000
CA = Certificate(subject="aegis-root-ca", issuer="aegis-root-ca", role="ca")
ARTIFACT_BYTES = b"policy-net.onnx -- pinned artifact content"
DIGEST = sha256_hex(ARTIFACT_BYTES)
OTHER_DIGEST = sha256_hex(b"malicious replacement weights")


def make_descriptor(
    digest: str = DIGEST, revision: str = "c354d75", artifact_id: str = "policy-vision-v1"
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        kind=ArtifactKind.POLICY,
        artifact_id=artifact_id,
        revision=revision,
        sha256=digest,
    )


class _NullSink:
    """Minimal SCAL sink; pinning tests don't inspect submissions."""

    def submit(self, command: TaskCommand, session_id: str) -> None: ...


def make_gateway(pin_store: ArtifactPinStore | None = None) -> ZeroTrustGateway:
    return ZeroTrustGateway(
        scal=_NullSink(),
        trust_store=TrustStore(ca_certificates=frozenset({CA})),
        pin_store=pin_store,
    )


def make_client_cert(subject: str = "fleet-client-alpha") -> Certificate:
    return Certificate(subject=subject, issuer="aegis-root-ca", role="operator")


def test_pinned_artifact_with_valid_lease_exposes_serving_surface() -> None:
    gateway = make_gateway()
    descriptor = make_descriptor()
    gateway.pin_store.pin(descriptor)

    surface_session = gateway.expose_serving_surface(
        ServingSurfaceKind.REMOTE_INFERENCE, descriptor, make_client_cert(), now_us=NOW_US
    )

    assert surface_session.surface is ServingSurfaceKind.REMOTE_INFERENCE
    assert surface_session.artifact is descriptor
    assert surface_session.lease.is_valid_at(NOW_US)
    # The exposed surface is bound to the same lease the envelope path checks.
    assert gateway.exposed_surface(surface_session.lease.session_id) is surface_session


def test_serving_traffic_rides_lease_and_nonce_path() -> None:
    gateway = make_gateway()
    descriptor = make_descriptor()
    gateway.pin_store.pin(descriptor)
    surface_session = gateway.expose_serving_surface(
        ServingSurfaceKind.ROBOT_SERVING, descriptor, make_client_cert(), now_us=NOW_US
    )

    envelope = CommandEnvelope(
        session_id=surface_session.lease.session_id,
        nonce="serve-1",
        sent_us=NOW_US,
        command=TaskCommand(primitive="MoveTo", params={"x": 1.0}, issued_us=NOW_US),
    )
    admitted = gateway.submit(envelope, now_us=NOW_US)
    assert admitted is envelope.command

    # Replay on the serving session is rejected like any other session.
    with pytest.raises(NonceError, match="replayed"):
        gateway.submit(envelope, now_us=NOW_US + 1)


def test_unpinned_artifact_refused() -> None:
    gateway = make_gateway()  # nothing pinned at all

    with pytest.raises(UnpinnedArtifactError, match="not pinned"):
        gateway.expose_serving_surface(
            ServingSurfaceKind.REMOTE_INFERENCE,
            make_descriptor(),
            make_client_cert(),
            now_us=NOW_US,
        )
    # Refusal left no session behind: the client cannot ride the refusal.
    assert gateway.exposed_surface("operator-alpha#0") is None


def test_hash_mismatch_refused() -> None:
    gateway = make_gateway()
    gateway.pin_store.pin(make_descriptor())

    forged = make_descriptor(digest=OTHER_DIGEST)
    with pytest.raises(ArtifactHashMismatchError, match="digest mismatch"):
        gateway.expose_serving_surface(
            ServingSurfaceKind.ROBOT_SERVING, forged, make_client_cert(), now_us=NOW_US
        )


def test_revision_mismatch_refused() -> None:
    gateway = make_gateway()
    gateway.pin_store.pin(make_descriptor())

    tampered = make_descriptor(revision="deadbee")
    with pytest.raises(ArtifactHashMismatchError, match="revision mismatch"):
        gateway.expose_serving_surface(
            ServingSurfaceKind.REMOTE_INFERENCE,
            tampered,
            make_client_cert(),
            now_us=NOW_US,
        )


def test_malformed_reference_refused() -> None:
    gateway = make_gateway()
    gateway.pin_store.pin(make_descriptor())

    for bad in (
        make_descriptor(digest="deadbeef"),  # not a full digest
        make_descriptor(digest=DIGEST.upper()),  # not lowercase hex
        make_descriptor(artifact_id=""),
        make_descriptor(revision="  "),
    ):
        with pytest.raises(ArtifactReferenceError):
            gateway.expose_serving_surface(
                ServingSurfaceKind.REMOTE_INFERENCE, bad, make_client_cert(), now_us=NOW_US
            )


def test_unauthenticated_client_cannot_expose_even_pinned_artifact() -> None:
    gateway = make_gateway()
    gateway.pin_store.pin(make_descriptor())

    rogue = Certificate(subject="attacker", issuer="rogue-ca", role="operator")
    with pytest.raises(AuthenticationError):
        gateway.expose_serving_surface(
            ServingSurfaceKind.REMOTE_INFERENCE, make_descriptor(), rogue, now_us=NOW_US
        )
    # Pinning passed but authentication refused — no surface exists anywhere.
    assert gateway.exposed_surface("attacker#0") is None


def test_unexposed_surface_is_unreachable() -> None:
    gateway = make_gateway()
    # No expose call at all: no session, no surface.
    assert gateway.exposed_surface("anything#1") is None


def test_pin_store_rejects_malformed_pins() -> None:
    store = ArtifactPinStore()
    with pytest.raises(ArtifactReferenceError):
        store.pin(make_descriptor(digest="nope"))
    with pytest.raises(ArtifactReferenceError):
        store.pin(make_descriptor(artifact_id=" "))


def test_sha256_hex_matches_reference_vector() -> None:
    assert sha256_hex(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
