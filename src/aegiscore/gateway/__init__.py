"""Public exports for the zero-trust communication gateway."""

from aegiscore.gateway.auth import (
    AuthenticationError,
    Certificate,
    PeerIdentity,
    TrustStore,
    authenticate_peer,
)
from aegiscore.gateway.gateway import (
    CommandEnvelope,
    EnvelopeError,
    LeaseExpiredError,
    NonceError,
    NonceRegistry,
    ScalSink,
    ServingSurfaceSession,
    SessionLease,
    SpySink,
    ZeroTrustGateway,
)
from aegiscore.gateway.pinning import (
    ArtifactDescriptor,
    ArtifactHashMismatchError,
    ArtifactKind,
    ArtifactPinStore,
    ArtifactReferenceError,
    PinningError,
    ServingSurfaceKind,
    UnpinnedArtifactError,
    sha256_hex,
)

__all__ = [
    "ArtifactDescriptor",
    "ArtifactHashMismatchError",
    "ArtifactKind",
    "ArtifactPinStore",
    "ArtifactReferenceError",
    "AuthenticationError",
    "Certificate",
    "CommandEnvelope",
    "EnvelopeError",
    "LeaseExpiredError",
    "NonceError",
    "NonceRegistry",
    "PeerIdentity",
    "PinningError",
    "ScalSink",
    "ServingSurfaceKind",
    "ServingSurfaceSession",
    "SessionLease",
    "SpySink",
    "TrustStore",
    "UnpinnedArtifactError",
    "ZeroTrustGateway",
    "authenticate_peer",
    "sha256_hex",
]
