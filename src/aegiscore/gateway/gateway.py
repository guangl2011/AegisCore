"""Zero-trust gateway: leases, nonce/replay rejection, and envelope assertion.

The gateway sits between operational software (operator or fleet client) and
SCAL. It is the only path by which a TaskCommand may reach SCAL, and it hands
a command downstream only after all envelope assertions pass:

1. the sending session is authenticated and holds a valid, unexpired lease;
2. the envelope carries a well-formed, never-before-seen nonce (replay
   rejection);
3. the envelope is internally consistent (session match, command age bound).

Skeleton scope: the protocol and its violation behaviour. Production crypto,
transport framing, and persistence of the nonce ledger are out of scope.

Time is monotonic microseconds (`now_us`) supplied by the caller, so every
behaviour is deterministic and CI-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aegiscore.core.model import TaskCommand
from aegiscore.gateway.auth import (
    AuthenticationError,
    Certificate,
    PeerIdentity,
    TrustStore,
    authenticate_peer,
)


class LeaseExpiredError(Exception):
    """Raised when a command arrives on a session whose lease has expired."""


class NonceError(Exception):
    """Raised when an envelope carries a malformed or already-seen nonce."""


class EnvelopeError(Exception):
    """Raised when an envelope fails a structural assertion."""


@dataclass(frozen=True)
class SessionLease:
    """Per-session authorisation to send commands until `expires_us`."""

    session_id: str
    subject: str
    expires_us: int

    def is_valid_at(self, now_us: int) -> bool:
        return now_us < self.expires_us


@dataclass(frozen=True)
class CommandEnvelope:
    """Wire envelope wrapping one TaskCommand for gateway admission."""

    session_id: str
    nonce: str
    sent_us: int
    command: TaskCommand


class ScalSink(Protocol):
    """The SCAL boundary: the only thing the gateway may call on admission."""

    def submit(self, command: TaskCommand, session_id: str) -> None: ...


class NonceRegistry:
    """Remembers every nonce already admitted, per session, forever.

    A bounded cache is the production design; the skeleton keeps the full
    ledger so replay behaviour is exactly "any repeated nonce is rejected".
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def check_and_record(self, session_id: str, nonce: str) -> None:
        """Reject malformed or replayed nonces; record fresh ones."""
        if not isinstance(nonce, str) or not nonce.strip():
            raise NonceError("nonce is missing or malformed")
        key = (session_id, nonce)
        if key in self._seen:
            raise NonceError(f"replayed nonce on session '{session_id}'")
        self._seen.add(key)


class ZeroTrustGateway:
    """Admission point for operator/fleet commands on the way to SCAL."""

    def __init__(
        self,
        scal: ScalSink,
        trust_store: TrustStore,
        client_role: str = "operator",
        lease_ttl_us: int = 5_000_000,  # 5 s of monotonic time
        max_command_age_us: int = 1_000_000,  # 1 s envelope freshness bound
    ) -> None:
        self._scal = scal
        self._trust_store = trust_store
        self._client_role = client_role
        self._lease_ttl_us = lease_ttl_us
        self._max_command_age_us = max_command_age_us
        self._sessions: dict[str, SessionLease] = {}
        self._nonces = NonceRegistry()

    def open_session(
        self, client_certificate: Certificate, now_us: int
    ) -> tuple[PeerIdentity, SessionLease]:
        """Authenticate a client and issue a fresh command lease."""
        identity = authenticate_peer(
            client_certificate, self._trust_store, expected_role=self._client_role
        )
        session_id = f"{identity.subject}#{now_us}"
        lease = SessionLease(
            session_id=session_id,
            subject=identity.subject,
            expires_us=now_us + self._lease_ttl_us,
        )
        self._sessions[session_id] = lease
        return identity, lease

    def submit(self, envelope: CommandEnvelope, now_us: int) -> TaskCommand:
        """Assert the envelope, then (only then) hand the command to SCAL."""
        lease = self._sessions.get(envelope.session_id)
        if lease is None:
            # No session exists for this sender: unauthenticated by construction.
            raise AuthenticationError(
                f"no authenticated session '{envelope.session_id}'"
            )
        if not lease.is_valid_at(now_us):
            raise LeaseExpiredError(
                f"lease for session '{envelope.session_id}' expired at "
                f"{lease.expires_us} (now {now_us})"
            )
        if envelope.session_id != lease.session_id or envelope.sent_us > now_us:
            raise EnvelopeError("envelope does not match its session or lies about time")
        if now_us - envelope.sent_us > self._max_command_age_us:
            raise EnvelopeError(
                f"command is stale: sent at {envelope.sent_us}, now {now_us}"
            )
        self._nonces.check_and_record(envelope.session_id, envelope.nonce)
        self._scal.submit(envelope.command, envelope.session_id)
        return envelope.command


class SpySink:
    """SCAL boundary test double that records every submission.

    Tests assert on `submitted` to prove whether a command did or did not
    reach SCAL.
    """

    def __init__(self) -> None:
        self.submitted: list[tuple[TaskCommand, str]] = []

    def submit(self, command: TaskCommand, session_id: str) -> None:
        self.submitted.append((command, session_id))
