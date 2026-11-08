"""Optional advisory perception/anomaly layer — OUTSIDE the command path.

Locked invariants (AegisCore spec, Nov 2026 OpenVINO design update):

- **No inference output may write or modify an actuator command.** This
  package produces :class:`AdvisoryConstraint` values and nothing else. The
  governor — the only actuator-command writer — consumes them as margin
  inputs through its own code and never imports this package (enforced in CI
  by ``scripts/check_import_graph.py``).
- **Optional extra only**: ``pip install aegiscore[advisory]``. physicalai is
  pinned to an exact version (pre-1.0, weekly releases); importing
  ``aegiscore.advisory`` never imports physicalai/onnxruntime — backend
  imports are lazy inside the factories, so the deterministic cores and CI
  run without them.
- Integration is against physicalai's **public documented APIs only** (no
  ``rtc.py`` internals, no ``_codec``), with model artifacts pinned to
  reviewed commit SHAs.
"""

from __future__ import annotations

from aegiscore.advisory.constraints import (
    AdvisoryConstraint,
    AdvisoryKind,
    pinned_model_ref,
    validate_source_model,
)
from aegiscore.advisory.factory import select_provider
from aegiscore.advisory.onnx_provider import (
    OnnxRuntimeAdvisoryProvider,
    create_onnx_provider,
)
from aegiscore.advisory.openvino_provider import (
    OpenVINOAdvisoryProvider,
    create_openvino_provider,
)
from aegiscore.advisory.provider import (
    AdvisoryProvider,
    NullAdvisoryProvider,
    ScoringAdvisoryProvider,
    scalar_score,
    severity_from_score,
)

__all__ = [
    "AdvisoryConstraint",
    "AdvisoryKind",
    "AdvisoryProvider",
    "NullAdvisoryProvider",
    "OnnxRuntimeAdvisoryProvider",
    "OpenVINOAdvisoryProvider",
    "ScoringAdvisoryProvider",
    "create_onnx_provider",
    "create_openvino_provider",
    "pinned_model_ref",
    "scalar_score",
    "select_provider",
    "severity_from_score",
    "validate_source_model",
]
