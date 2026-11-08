"""Artifact pinning for gateway-exposed serving surfaces.

physicalai serving surfaces (remote inference, robot serving) are reachable
only behind the gateway's mTLS, session-lease, and nonce/replay path, and only
with a hash-pinned artifact: a model or policy artifact identified by
(SHA-256 digest, revision) that the operator registered beforehand. An
unpinned or mismatched artifact is refused — the gateway never exposes a
serving surface whose code provenance it cannot vouch for.

This is the pinning protocol, not artifact transport: the gateway never
downloads or executes anything here. Weight licenses and artifact content are
recorded by the operator at pin time (per the spec's locked decisions).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

_SHA256_HEX_LENGTH = 64


class ServingSurfaceKind(StrEnum):
    """physicalai serving surfaces the gateway can expose."""

    REMOTE_INFERENCE = "remote_inference"
    ROBOT_SERVING = "robot_serving"


class ArtifactKind(StrEnum):
    """The artifact classes that may gate a serving surface."""

    MODEL = "model"
    POLICY = "policy"


class PinningError(Exception):
    """Base class for artifact-pinning violations."""


class UnpinnedArtifactError(PinningError):
    """Raised when an artifact was never pinned (or pinned under another id)."""


class ArtifactHashMismatchError(PinningError):
    """Raised when an artifact's digest or revision disagrees with the pin."""


class ArtifactReferenceError(PinningError):
    """Raised when an artifact reference is malformed (bad id, revision, or digest)."""


@dataclass(frozen=True)
class ArtifactDescriptor:
    """A reference to one model/policy artifact at the gateway boundary.

    `sha256` is the lowercase hex digest of the artifact's bytes; `revision`
    is the upstream revision the artifact was taken from (e.g. a commit hash),
    pinned together with the digest per the spec's locked decisions.
    """

    kind: ArtifactKind
    artifact_id: str
    revision: str
    sha256: str


def sha256_hex(content: bytes) -> str:
    """Lowercase hex SHA-256 of artifact bytes."""
    return hashlib.sha256(content).hexdigest()


def validate_descriptor(descriptor: ArtifactDescriptor) -> None:
    """Raise ArtifactReferenceError unless the descriptor is well-formed."""
    if not descriptor.artifact_id or not descriptor.artifact_id.strip():
        raise ArtifactReferenceError("artifact_id is missing")
    if not descriptor.revision or not descriptor.revision.strip():
        raise ArtifactReferenceError("revision is missing")
    digest = descriptor.sha256
    if len(digest) != _SHA256_HEX_LENGTH or any(c not in "0123456789abcdef" for c in digest):
        raise ArtifactReferenceError(
            f"sha256 must be a 64-char lowercase hex digest, got {digest!r}"
        )


class ArtifactPinStore:
    """Operator-registered set of approved (artifact_id -> digest, revision) pins."""

    def __init__(self) -> None:
        self._pins: dict[tuple[ArtifactKind, str], ArtifactDescriptor] = {}

    def pin(self, descriptor: ArtifactDescriptor) -> None:
        """Register a well-formed artifact descriptor as the approved pin."""
        validate_descriptor(descriptor)
        key = (descriptor.kind, descriptor.artifact_id)
        self._pins[key] = descriptor

    def is_pinned(self, kind: ArtifactKind, artifact_id: str) -> bool:
        return (kind, artifact_id) in self._pins

    def expected(self, kind: ArtifactKind, artifact_id: str) -> ArtifactDescriptor | None:
        """The approved pin for an artifact id, or None when never pinned."""
        return self._pins.get((kind, artifact_id))

    def verify(self, descriptor: ArtifactDescriptor) -> None:
        """Assert the descriptor matches its registered pin.

        Raises UnpinnedArtifactError when the artifact was never pinned, and
        ArtifactHashMismatchError when its digest or revision disagrees with
        the pin.
        """
        validate_descriptor(descriptor)
        registered = self._pins.get((descriptor.kind, descriptor.artifact_id))
        if registered is None:
            raise UnpinnedArtifactError(
                f"{descriptor.kind.value} artifact '{descriptor.artifact_id}' "
                "is not pinned; refusing to expose a serving surface for it"
            )
        if registered.sha256 != descriptor.sha256:
            raise ArtifactHashMismatchError(
                f"{descriptor.kind.value} artifact '{descriptor.artifact_id}' "
                f"digest mismatch: pinned {registered.sha256}, "
                f"presented {descriptor.sha256}"
            )
        if registered.revision != descriptor.revision:
            raise ArtifactHashMismatchError(
                f"{descriptor.kind.value} artifact '{descriptor.artifact_id}' "
                f"revision mismatch: pinned {registered.revision}, "
                f"presented {descriptor.revision}"
            )
