"""Provider selection — the fallback chain that keeps advisory optional.

Chain (spec locked decisions): OpenVINO/physicalai when installed (degrading
silently to CPU when the requested accelerator is missing), then onnxruntime
when OpenVINO is absent, then :class:`NullAdvisoryProvider` when no runtime
exists at all. The command path never depends on the advisory layer existing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aegiscore.advisory.constraints import AdvisoryConstraint, AdvisoryKind
from aegiscore.advisory.onnx_provider import OnnxRuntimeAdvisoryProvider
from aegiscore.advisory.onnx_provider import (
    create_onnx_provider as _create_onnx_provider,
)
from aegiscore.advisory.openvino_provider import OpenVINOAdvisoryProvider
from aegiscore.advisory.openvino_provider import (
    create_openvino_provider as _create_openvino_provider,
)
from aegiscore.advisory.provider import AdvisoryProvider, NullAdvisoryProvider

ObsFn = Callable[[Any], Any]
ReadFrame = Callable[[], Any]
Clock = Callable[[], int]


def select_provider(
    *,
    export_dir: str | Path,
    kind: AdvisoryKind | str,
    model_ref: str,
    read_frame: ReadFrame,
    onnx_model_path: str | None = None,
    camera: Any | None = None,
    obs_fn: ObsFn | None = None,
    device: str = "NPU",
    policy_name: str | None = None,
    score_fn: Any = None,
    min_severity: float = 0.0,
    clock: Clock | None = None,
    onnx_input_name: str | None = None,
    onnx_providers: Sequence[str] | None = None,
) -> AdvisoryProvider:
    """Build the best available advisory provider, degrading silently.

    Only ``ImportError`` — the runtime-dependency-absent signal — advances the
    chain; a broken model path or a failed CPU compile propagates, because a
    misconfigured model is an operator error, not a degrade condition.
    """
    try:
        return _create_openvino_provider(
            export_dir=export_dir,
            kind=kind,
            model_ref=model_ref,
            camera=camera,
            read_frame=read_frame,
            obs_fn=obs_fn,
            device=device,
            policy_name=policy_name,
            score_fn=score_fn,
            min_severity=min_severity,
            clock=clock,
        )
    except ImportError:
        pass  # physicalai/openvino not installed — expected on non-Intel hosts

    if onnx_model_path is None:
        return NullAdvisoryProvider()
    try:
        return _create_onnx_provider(
            model_path=onnx_model_path,
            kind=kind,
            model_ref=model_ref,
            read_frame=read_frame,
            input_name=onnx_input_name,
            providers=onnx_providers,
            obs_fn=obs_fn,
            score_fn=score_fn,
            min_severity=min_severity,
            clock=clock,
        )
    except ImportError:
        return NullAdvisoryProvider()


__all__ = [
    "AdvisoryConstraint",
    "AdvisoryKind",
    "AdvisoryProvider",
    "NullAdvisoryProvider",
    "OnnxRuntimeAdvisoryProvider",
    "OpenVINOAdvisoryProvider",
    "select_provider",
]
