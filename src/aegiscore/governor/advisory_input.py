"""Structural view of advisory constraints — the governor's only advisory API.

Spec deliverable 7 (AegisCore MVP spec, Nov 2026 OpenVINO design update). The
governor consumes advisory constraints **as margin inputs only**, through its
own code. It defines a structural view of the four constraint fields here
instead of importing ``aegiscore.advisory`` — the deterministic cores stay
import-free from the optional advisory package (CI-enforced by
``scripts/check_import_graph.py``), and any object with the right fields (the
advisory package's ``AdvisoryConstraint`` included) is accepted.

The invariant this module protects: **an advisory constraint can never express
an actuator command.** The view has exactly four fields; nothing in it is a
command, a command modifier, or a bypass of an envelope check.
"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Any, Protocol


#: Kinds the governor's margin map understands — mirrors AdvisoryKind in the
#: advisory package (duplicated as literals to keep the import boundary).
class AdvisorySignalKind(StrEnum):
    PROXIMITY_MARGIN = "proximity_margin"
    ANOMALY_FLAG = "anomaly_flag"
    TERRAIN_RISK = "terrain_risk"


ADVISORY_KIND_VALUES = frozenset(k.value for k in AdvisorySignalKind)


class AdvisorySignal(Protocol):
    """Structural view of ``aegiscore.advisory.AdvisoryConstraint``."""

    kind: str
    severity: float  # 0..1 — 1.0 means zero remaining margin
    source_model: str  # pinned artifact reference "<model-id>@<hex-revision>"
    issued_monotonic_ns: int  # time.monotonic_ns() at production time


class AdvisoryInputError(ValueError):
    """A malformed advisory constraint was offered to the governor."""


def normalize_advisory(signal: Any) -> tuple[str, float, int]:
    """Validate one advisory-shaped object; return ``(kind, severity, issued_ns)``.

    Raises :class:`AdvisoryInputError` for anything the margin map cannot
    consume: unknown kind, non-finite or out-of-range severity, non-integer
    issue time. The governor never trusts partially valid input — a malformed
    constraint is rejected whole, like a malformed command envelope.
    """
    if signal is None or isinstance(signal, (str, bytes)):
        raise AdvisoryInputError(
            f"advisory constraint must be an object, got {type(signal).__name__}"
        )

    kind = getattr(signal, "kind", None)
    if isinstance(kind, StrEnum):
        kind = kind.value
    if not isinstance(kind, str) or kind not in ADVISORY_KIND_VALUES:
        raise AdvisoryInputError(
            f"advisory kind must be one of {sorted(ADVISORY_KIND_VALUES)}, got {kind!r}"
        )

    severity = getattr(signal, "severity", None)
    if isinstance(severity, bool) or not isinstance(severity, (int, float)):
        raise AdvisoryInputError(
            f"advisory severity must be a real number, got {type(severity).__name__}"
        )
    severity = float(severity)
    if not isfinite(severity) or not 0.0 <= severity <= 1.0:
        raise AdvisoryInputError(f"advisory severity must be finite in [0, 1], got {severity}")

    issued_ns = getattr(signal, "issued_monotonic_ns", None)
    if isinstance(issued_ns, bool) or not isinstance(issued_ns, int):
        raise AdvisoryInputError(
            f"advisory issued_monotonic_ns must be an int, got {type(issued_ns).__name__}"
        )
    if issued_ns < 0:
        raise AdvisoryInputError(
            f"advisory issued_monotonic_ns must be non-negative, got {issued_ns}"
        )

    return kind, severity, issued_ns
