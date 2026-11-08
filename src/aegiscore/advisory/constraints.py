"""Advisory constraint types — the advisory layer's entire output vocabulary.

Spec deliverable 7 (AegisCore MVP + NSF pitch spec, OpenVINO design update).
The advisory layer is optional perception/anomaly inference (physicalai/
OpenVINO on Intel edge hardware, onnxruntime fallback) that sits OUTSIDE the
command path. Its only product is an :class:`AdvisoryConstraint`: a named risk
signal the governor may consume to narrow margins it already owns.

No type in this module can express an actuator command — the governor is the
only writer of actuator commands (``aegiscore.core.model.ActuatorCommand``),
and nothing in the advisory package imports or references it. The governor
defines its own structural view of these fields, so this package stays
import-free from the deterministic cores (enforced in CI by
``scripts/check_import_graph.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class AdvisoryKind(StrEnum):
    """Kinds of advisory signal the governor's margin map understands."""

    PROXIMITY_MARGIN = "proximity_margin"
    ANOMALY_FLAG = "anomaly_flag"
    TERRAIN_RISK = "terrain_risk"


# source_model must name a pinned artifact: "<model-id>@<revision>" where the
# revision is a hex commit SHA (7-64 chars; full 40-char SHAs recommended —
# the integration findings require reviewed-SHA pinning for HF artifacts).
_SOURCE_MODEL_RE = re.compile(r"^[^@\s]+@[0-9a-fA-F]{7,64}$")


def validate_source_model(ref: str) -> str:
    """Return *ref* if it names a pinned artifact; raise ``ValueError`` otherwise.

    Every constraint carries the model that produced it, and the model must be
    pinned: an unpinned (or hash-mismatched) artifact is exactly the supply
    chain the zero-trust gateway refuses at its boundary (deliverable 8).
    """
    if not isinstance(ref, str) or not _SOURCE_MODEL_RE.fullmatch(ref):
        msg = (
            f"source_model must look like '<model-id>@<hex-revision>' with a "
            f"7-64 char hex revision, got {ref!r}"
        )
        raise ValueError(msg)
    return ref


def pinned_model_ref(model_id: str, revision: str) -> str:
    """Format a pinned artifact reference, e.g. ``OpenVINO/model@<sha>``.

    Use full commit SHAs (Hugging Face ``revision=``), not tags or branch
    names — tags move, SHAs are reviewable.
    """
    return validate_source_model(f"{model_id}@{revision}")


@dataclass(frozen=True)
class AdvisoryConstraint:
    """One advisory signal. **Advisory only — never a command source.**

    Fields mirror the spec's interface contract. The governor consumes these
    as margin inputs through its own code (``margin[kind] = min(margin[kind],
    1 - severity)``; zero margin descends the failover ladder), and checks
    ``issued_monotonic_ns`` for freshness like any other sensor reading.
    Higher severity means less remaining margin.
    """

    kind: AdvisoryKind
    severity: float  # 0..1 — risk level; 1.0 = zero remaining margin
    source_model: str  # "<model-id>@<hex-revision>" — pinned artifact
    issued_monotonic_ns: int  # time.monotonic_ns() at production time

    def __post_init__(self) -> None:
        # Coerce the spec's literal strings ("proximity_margin", ...) onto the
        # enum so callers can pass either; reject anything else.
        if not isinstance(self.kind, AdvisoryKind):
            try:
                coerced = AdvisoryKind(self.kind)
            except ValueError as exc:
                allowed = [k.value for k in AdvisoryKind]
                msg = f"kind must be one of {allowed}, got {self.kind!r}"
                raise ValueError(msg) from exc
            object.__setattr__(self, "kind", coerced)

        if isinstance(self.severity, bool) or not isinstance(self.severity, (int, float)):
            msg = f"severity must be a real number, got {type(self.severity).__name__}"
            raise TypeError(msg)
        object.__setattr__(self, "severity", float(self.severity))
        if not isfinite(self.severity) or not 0.0 <= self.severity <= 1.0:
            msg = f"severity must be a finite value in [0, 1], got {self.severity}"
            raise ValueError(msg)

        if isinstance(self.issued_monotonic_ns, bool) or not isinstance(
            self.issued_monotonic_ns, int
        ):
            msg = (
                "issued_monotonic_ns must be an int (time.monotonic_ns()), "
                f"got {type(self.issued_monotonic_ns).__name__}"
            )
            raise TypeError(msg)
        if self.issued_monotonic_ns < 0:
            msg = f"issued_monotonic_ns must be non-negative, got {self.issued_monotonic_ns}"
            raise ValueError(msg)

        validate_source_model(self.source_model)
