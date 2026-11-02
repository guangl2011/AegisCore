"""Failover state machine: the six-rung safety ladder.

Spec state table (AegisCore MVP spec, deliverable 2)::

    NOMINAL -> FILTERED -> CONSERVATIVE -> HOLD -> CONTROLLED_STOP -> E_STOP

Transition rules enforced here — the closed relation the FSM property test
exercises:

- **Faults never ascend.** Fault-driven transitions descend the ladder. Except
  for emergency faults (braking-authority loss, proximal e-stop), which jump
  straight to E_STOP from any state, a *sustained* fault walks exactly one rung
  per cycle toward the fault's mapped state — no descent skips. A *transient*
  fault therefore dips one rung and recovers through the table exits instead.
- **Recovery exits exist only in the upper rungs**, exactly as the spec table
  lists them: FILTERED->NOMINAL (margins recover), CONSERVATIVE->NOMINAL
  (recovery streak), HOLD->CONSERVATIVE (lease restored). No automatic ascent
  crosses into or out of CONTROLLED_STOP.
- **Re-arm is operator-authorised only, only from CONTROLLED_STOP**, and lands
  on CONSERVATIVE — resume cautiously, then recover to NOMINAL through the
  normal path. E_STOP is terminal in software: the spec's "physical re-arm" is
  a hardware path outside this state machine.

"Descent-only" therefore means: a fault can never move the mode up the ladder,
and the only upward edges are the table's recovery exits plus the operator
re-arm — never a fault, never an implicit timeout.
"""

from __future__ import annotations

from dataclasses import dataclass

from aegiscore.core.model import GovMode

LADDER: tuple[GovMode, ...] = (
    GovMode.NOMINAL,
    GovMode.FILTERED,
    GovMode.CONSERVATIVE,
    GovMode.HOLD,
    GovMode.CONTROLLED_STOP,
    GovMode.E_STOP,
)

RE_ARM_TARGET = GovMode.CONSERVATIVE

# The spec table's automatic recovery exits (upper rungs only).
RECOVERY_EDGES: frozenset[tuple[GovMode, GovMode]] = frozenset(
    {
        (GovMode.FILTERED, GovMode.NOMINAL),
        (GovMode.CONSERVATIVE, GovMode.NOMINAL),
        (GovMode.HOLD, GovMode.CONSERVATIVE),
    }
)


@dataclass(frozen=True)
class TransitionAudit:
    """One recorded mode change, for forensics and property tests."""

    from_mode: GovMode
    to_mode: GovMode
    kind: str  # "descent" | "emergency" | "recovery" | "re_arm"
    reason: str | None = None


class FailoverFSM:
    """Six-state failover ladder with a closed, testable transition relation."""

    def __init__(self) -> None:
        self._mode = GovMode.NOMINAL
        self._audit: list[TransitionAudit] = []

    @property
    def mode(self) -> GovMode:
        return self._mode

    @property
    def audit(self) -> tuple[TransitionAudit, ...]:
        return tuple(self._audit)

    def demand_descend(self, target: GovMode, reason: str | None = None) -> GovMode:
        """Descend exactly one rung toward ``target``; never ascends, never skips.

        Sustained faults call this every cycle and walk down to their mapped
        state; the governor couples each demand to the ladder at most one rung
        per cycle, so a multi-rung demand is reached over successive cycles.
        """
        cur = LADDER.index(self._mode)
        tgt = LADDER.index(target)
        if tgt <= cur:
            return self._mode
        self._apply(LADDER[cur + 1], "descent", reason)
        return self._mode

    def demand_emergency(self, reason: str | None = None) -> GovMode:
        """Emergency faults jump directly to E_STOP from any state."""
        self._apply(GovMode.E_STOP, "emergency", reason)
        return self._mode

    def try_recover(self, target: GovMode, reason: str | None = None) -> bool:
        """Apply a table recovery exit if that edge exists from the current mode."""
        if (self._mode, target) not in RECOVERY_EDGES:
            return False
        self._apply(target, "recovery", reason)
        return True

    def re_arm(self, operator_authorised: bool) -> bool:
        """Operator-authorised re-arm; only valid from CONTROLLED_STOP."""
        if not operator_authorised or self._mode is not GovMode.CONTROLLED_STOP:
            return False
        self._apply(RE_ARM_TARGET, "re_arm", "operator_re_arm")
        return True

    def _apply(self, to: GovMode, kind: str, reason: str | None) -> None:
        if to is self._mode:
            return
        self._audit.append(TransitionAudit(self._mode, to, kind, reason))
        self._mode = to
