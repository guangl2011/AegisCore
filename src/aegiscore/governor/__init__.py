"""Governor: deterministic safety-bounded command governor core.

Public API:

- :class:`GovernorCore` — the supervisor cycle; the only writer of actuator
  commands.
- :class:`GovernorConfig` — deterministic thresholds for one governor instance.
- :class:`Fault` — fault-injection classes driven by the bench harness.
- :class:`FailoverFSM` — the six-rung failover ladder and its closed transition
  relation.
- :class:`SafetyLog` / :class:`SafetyLogRecord` — one decision record per cycle.
- :class:`AdvisorySignal` / :class:`AdvisorySignalKind` / :class:`AdvisoryInputError`
  — the governor's structural view of advisory constraints (deliverable 7):
  margin inputs only, never a command source, with no dependency on the
  optional ``aegiscore.advisory`` package.
"""

from aegiscore.core.model import GovMode
from aegiscore.governor.advisory_input import (
    ADVISORY_KIND_VALUES,
    AdvisoryInputError,
    AdvisorySignal,
    AdvisorySignalKind,
    normalize_advisory,
)
from aegiscore.governor.config import GovernorConfig
from aegiscore.governor.faults import Fault
from aegiscore.governor.fsm import (
    LADDER,
    RE_ARM_TARGET,
    RECOVERY_EDGES,
    FailoverFSM,
    TransitionAudit,
)
from aegiscore.governor.governor import GovernorCore
from aegiscore.governor.safety_log import SafetyLog, SafetyLogRecord

__all__ = [
    "ADVISORY_KIND_VALUES",
    "LADDER",
    "RECOVERY_EDGES",
    "RE_ARM_TARGET",
    "AdvisoryInputError",
    "AdvisorySignal",
    "AdvisorySignalKind",
    "FailoverFSM",
    "Fault",
    "GovernorConfig",
    "GovernorCore",
    "GovMode",
    "SafetyLog",
    "SafetyLogRecord",
    "TransitionAudit",
    "normalize_advisory",
]
