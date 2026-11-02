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
    SessionLease,
    SpySink,
    ZeroTrustGateway,
)

__all__ = [
    "AuthenticationError",
    "Certificate",
    "CommandEnvelope",
    "EnvelopeError",
    "LeaseExpiredError",
    "NonceError",
    "NonceRegistry",
    "PeerIdentity",
    "ScalSink",
    "SessionLease",
    "SpySink",
    "TrustStore",
    "ZeroTrustGateway",
    "authenticate_peer",
]
