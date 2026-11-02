"""Append-only safety log: one decision record per supervisor cycle."""

from __future__ import annotations

from dataclasses import dataclass, field

from aegiscore.core.model import GovMode


@dataclass(frozen=True)
class SafetyLogRecord:
    """Immutable record of one deterministic supervisor cycle.

    Together with the completeness invariant (exactly one record per
    ``GovernorCore.step`` call, including fault and E_STOP cycles) this is the
    MVP form of the spec's "100% deterministic safety logging".
    """

    seq: int
    timestamp_us: int
    mode: GovMode  # post-decision mode
    admitted_actuator_id: str | None
    admitted_command_type: str | None
    admitted_value: float | None
    margins: dict[str, float] = field(default_factory=dict)
    reason: str | None = None
    transition_from: GovMode | None = None  # None when no transition this cycle
    transition_to: GovMode | None = None
    latency_us: float = 0.0


class SafetyLog:
    """In-memory append-only safety log.

    Production hardening (bounded ring buffer, durable sink) is hardware-phase
    work; the MVP guarantees the completeness invariant and record immutability.
    """

    def __init__(self) -> None:
        self._records: list[SafetyLogRecord] = []

    def append(self, record: SafetyLogRecord) -> None:
        self._records.append(record)

    @property
    def records(self) -> tuple[SafetyLogRecord, ...]:
        return tuple(self._records)

    def transitions(self) -> tuple[SafetyLogRecord, ...]:
        """Records on which the failover mode changed."""
        return tuple(r for r in self._records if r.transition_to is not None)

    def __len__(self) -> int:
        return len(self._records)
