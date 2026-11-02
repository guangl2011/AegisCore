"""Certificate-based mutual authentication for the zero-trust gateway.

In-sim protocol only: certificates are plain dataclasses and trust is a set of
CA certificates held by the gateway. Production PKI (X.509 parsing, key
signatures, revocation) is explicitly out of scope for this skeleton; what the
skeleton must prove is the *behaviour*: no command from an unauthenticated peer
ever crosses the gateway boundary.

Time is monotonic microseconds (`now_us`) passed in by the caller, matching the
core model — no wall clock, so tests and the bench harness stay deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class AuthenticationError(Exception):
    """Raised when a peer cannot be authenticated."""


@dataclass(frozen=True)
class Certificate:
    """In-sim stand-in for an X.509 certificate.

    `subject` names the peer; `issuer` names the CA that vouched for it. A real
    implementation would verify a signature chain; here trust is membership of
    the issuing CA in the peer's trust store.
    """

    subject: str
    issuer: str
    role: str  # e.g. "operator", "fleet-client", "gateway", "ca"


@dataclass(frozen=True)
class TrustStore:
    """The set of CA certificates a peer trusts to vouch for others."""

    ca_certificates: frozenset[Certificate] = field(default_factory=frozenset)

    def issues(self, certificate: Certificate) -> bool:
        return any(
            ca.subject == certificate.issuer and ca.role == "ca"
            for ca in self.ca_certificates
        )


@dataclass(frozen=True)
class PeerIdentity:
    """Authenticated identity of the remote peer after a successful handshake."""

    subject: str
    role: str


def authenticate_peer(
    peer_certificate: Certificate,
    trust_store: TrustStore,
    expected_role: str | None = None,
) -> PeerIdentity:
    """Validate a peer certificate against the trust store.

    Mutual authentication: the gateway presents its own certificate to the
    client separately (it is configured, not negotiated, in-sim), and every
    client must pass this check before a session exists.

    Raises AuthenticationError when the certificate is not issued by a trusted
    CA or carries a role the gateway does not accept from that peer.
    """
    if not trust_store.issues(peer_certificate):
        raise AuthenticationError(
            f"certificate for '{peer_certificate.subject}' "
            f"issued by untrusted CA '{peer_certificate.issuer}'"
        )
    if expected_role is not None and peer_certificate.role != expected_role:
        raise AuthenticationError(
            f"certificate for '{peer_certificate.subject}' has role "
            f"'{peer_certificate.role}', expected '{expected_role}'"
        )
    return PeerIdentity(subject=peer_certificate.subject, role=peer_certificate.role)
