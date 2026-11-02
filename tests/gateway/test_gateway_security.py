"""Gateway security suite: mutual auth, leases, and replay rejection.

Each test exercises one violation behaviour of the zero-trust gateway. The
SCAL boundary is a SpySink; an empty `submitted` list after a rejection proves
the command never reached SCAL.
"""

import pytest

from aegiscore.core.model import TaskCommand
from aegiscore.gateway import (
    AuthenticationError,
    Certificate,
    CommandEnvelope,
    EnvelopeError,
    LeaseExpiredError,
    NonceError,
    SpySink,
    TrustStore,
    ZeroTrustGateway,
    authenticate_peer,
)

NOW_US = 1_000_000_000  # arbitrary fixed monotonic timestamp
CA = Certificate(subject="aegis-root-ca", issuer="aegis-root-ca", role="ca")
GATEWAY_CERT = Certificate(
    subject="edge-gateway-01", issuer="aegis-root-ca", role="gateway"
)


def make_client_cert(subject: str = "operator-alpha") -> Certificate:
    return Certificate(subject=subject, issuer="aegis-root-ca", role="operator")


def make_gateway() -> tuple[ZeroTrustGateway, SpySink]:
    sink = SpySink()
    gateway = ZeroTrustGateway(
        scal=sink, trust_store=TrustStore(ca_certificates=frozenset({CA}))
    )
    return gateway, sink


def make_envelope(lease, nonce: str, sent_us: int = NOW_US) -> CommandEnvelope:
    return CommandEnvelope(
        session_id=lease.session_id,
        nonce=nonce,
        sent_us=sent_us,
        command=TaskCommand(primitive="MoveTo", params={"x": 1.0}, issued_us=sent_us),
    )


def open_session(gateway: ZeroTrustGateway, cert: Certificate | None = None):
    return gateway.open_session(cert or make_client_cert(), now_us=NOW_US)


def test_mutual_auth_rejects_untrusted_certificate() -> None:
    # The gateway's own certificate validates against the same trust store —
    # the mutual direction of the handshake.
    gateway_identity = authenticate_peer(
        GATEWAY_CERT, TrustStore(ca_certificates=frozenset({CA})), expected_role="gateway"
    )
    assert gateway_identity.subject == "edge-gateway-01"

    rogue_client = Certificate(
        subject="attacker", issuer="rogue-ca", role="operator"
    )
    with pytest.raises(AuthenticationError):
        authenticate_peer(rogue_client, TrustStore(ca_certificates=frozenset({CA})))
    # And even an honest CA cannot mint an operator with the wrong role.
    with pytest.raises(AuthenticationError):
        authenticate_peer(
            Certificate(subject="impersonator", issuer="aegis-root-ca", role="gateway"),
            TrustStore(ca_certificates=frozenset({CA})),
            expected_role="operator",
        )


def test_valid_authenticated_fresh_command_reaches_scal() -> None:
    gateway, sink = make_gateway()
    _, lease = open_session(gateway)

    envelope = make_envelope(lease, nonce="nonce-1")
    admitted = gateway.submit(envelope, now_us=NOW_US)

    assert admitted is envelope.command
    assert len(sink.submitted) == 1
    reached_command, reached_session = sink.submitted[0]
    assert reached_command is envelope.command
    assert reached_session == lease.session_id


def test_replayed_command_rejected() -> None:
    gateway, sink = make_gateway()
    _, lease = open_session(gateway)

    first = make_envelope(lease, nonce="nonce-1")
    gateway.submit(first, now_us=NOW_US)
    with pytest.raises(NonceError, match="replayed"):
        gateway.submit(first, now_us=NOW_US + 1)  # same nonce, same session
    assert len(sink.submitted) == 1  # only the original got through


def test_expired_lease_rejected() -> None:
    gateway, sink = make_gateway()
    _, lease = open_session(gateway)

    envelope = make_envelope(lease, nonce="nonce-1", sent_us=NOW_US + 10)
    with pytest.raises(LeaseExpiredError):
        gateway.submit(envelope, now_us=lease.expires_us)  # exactly at expiry
    assert sink.submitted == []


def test_invalid_nonce_rejected() -> None:
    gateway, sink = make_gateway()
    _, lease = open_session(gateway)

    for bad_nonce in ("", "   "):
        with pytest.raises(NonceError, match="malformed"):
            gateway.submit(make_envelope(lease, nonce=bad_nonce), now_us=NOW_US)
    assert sink.submitted == []


def test_unauthenticated_command_never_reaches_scal() -> None:
    gateway, sink = make_gateway()

    # An envelope claiming a session that was never authenticated: no
    # open_session call happened at all.
    forged = CommandEnvelope(
        session_id="operator-alpha#999",
        nonce="nonce-1",
        sent_us=NOW_US,
        command=TaskCommand(primitive="SetBlade", params={"on": 1.0}, issued_us=NOW_US),
    )
    with pytest.raises(AuthenticationError):
        gateway.submit(forged, now_us=NOW_US)
    assert sink.submitted == []


def test_stale_command_rejected_as_envelope_violation() -> None:
    gateway, sink = make_gateway()
    _, lease = open_session(gateway)

    envelope = make_envelope(lease, nonce="nonce-1", sent_us=NOW_US - 2_000_000)
    with pytest.raises(EnvelopeError, match="stale"):
        gateway.submit(envelope, now_us=NOW_US)
    assert sink.submitted == []
