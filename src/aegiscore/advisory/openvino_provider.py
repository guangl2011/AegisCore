"""physicalai/OpenVINO-backed advisory provider — the optional, pinned backend.

Integration surface — public documented APIs only (docs.openvino.ai/2026/
physical-ai; findings artifact art_1H1pZ1s7, physicalai v0.4.0):

- ``physicalai.inference.InferenceModel(export_dir, policy_name=...,
  backend="openvino", device=...)`` — the manifest-defined model pipeline
  (observation → preprocessors → runner → postprocessors) compiled for
  CPU / GPU / NPU by physicalai's OpenVINO adapter.
- A physicalai ``Camera`` object's ``read_latest()`` (unified Camera API,
  monotonic frame timestamps) as the default frame source.

Nothing from private modules (``rtc.py`` internals, ``_codec``) is touched.
physicalai is an optional extra pinned to an exact version (pyproject:
``advisory``), because the project is pre-1.0 with weekly releases and
in-window breaking deprecations. Importing this module never imports
physicalai — the import happens inside :func:`create_openvino_provider`, so
the advisory test suite runs in CI with stub backends only.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from aegiscore.advisory.constraints import AdvisoryKind
from aegiscore.advisory.provider import ScoringAdvisoryProvider, scalar_score

if TYPE_CHECKING:  # type-only: keeps physicalai off the runtime import path
    from physicalai.capture import Camera

ObsFn = Callable[[Any], Any]
ReadFrame = Callable[[], Any]


@runtime_checkable
class InferenceModelLike(Protocol):
    """Structural view of the documented ``physicalai.inference.InferenceModel``.

    Only the public lifecycle appears here (``select_action`` / ``close``);
    submethods and adapter internals are never used.
    """

    def select_action(self, observation: Any) -> Any: ...

    def close(self) -> None: ...


class OpenVINOAdvisoryProvider(ScoringAdvisoryProvider):
    """Advisory scoring through a physicalai ``InferenceModel`` (OpenVINO backend).

    The exported model must reduce to a single scalar risk score per
    observation (``scalar_score`` handles numpy scalars/arrays and
    single-entry dicts); ``obs_fn`` shapes the frame for models whose
    manifest declares a structured observation — by default the raw frame
    data is passed through, letting the manifest's own preprocessors do the
    model-specific shaping.
    """

    def __init__(
        self,
        *,
        model: InferenceModelLike,
        obs_fn: ObsFn | None = None,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(**base_kwargs)
        self._model = model
        self._obs_fn = obs_fn

    def _score(self, frame_data: Any) -> float:
        observation = frame_data if self._obs_fn is None else self._obs_fn(frame_data)
        return scalar_score(self._model.select_action(observation))

    def _on_close(self) -> None:
        self._model.close()


def create_openvino_provider(
    *,
    export_dir: str | Path,
    kind: AdvisoryKind | str,
    model_ref: str,
    camera: Camera | None = None,
    read_frame: ReadFrame | None = None,
    obs_fn: ObsFn | None = None,
    device: str = "NPU",
    policy_name: str | None = None,
    score_fn: Any = None,
    min_severity: float = 0.0,
    clock: Any = None,
) -> OpenVINOAdvisoryProvider:
    """Build an OpenVINO-backed provider against a live physicalai install.

    Device degrade (silent): OpenVINO compilation raises ``RuntimeError`` when
    the requested device has no working plugin/driver — no NPU device, iGPU
    without the OpenCL runtime — and the adapter's own error text recommends
    ``device='CPU'`` as the remedy. On ``RuntimeError`` we retry on CPU and
    record ``degraded=True``; the provider is advisory, so an unavailable
    accelerator must never block operation. An ``ImportError`` (physicalai or
    openvino not installed) propagates: ``select_provider`` turns that into
    the onnxruntime fallback.
    """
    from physicalai.inference import InferenceModel  # public documented API

    if read_frame is None and camera is not None:
        read_frame = camera.read_latest
    if read_frame is None:
        msg = (
            "advisory provider needs an input source: pass camera= (a "
            "physicalai Camera) or read_frame= (any callable returning a "
            "Frame-like object, e.g. a telemetry window)"
        )
        raise ValueError(msg)

    requested = device.upper() or "CPU"
    try:
        model = InferenceModel(
            export_dir, policy_name=policy_name, backend="openvino", device=requested
        )
    except RuntimeError:
        # Requested accelerator unavailable — silently degrade to CPU.
        model = InferenceModel(
            export_dir, policy_name=policy_name, backend="openvino", device="CPU"
        )
        requested, degraded = "CPU", True
    else:
        degraded = False

    return OpenVINOAdvisoryProvider(
        model=model,
        obs_fn=obs_fn,
        kind=kind,
        model_ref=model_ref,
        read_frame=read_frame,
        device=requested,
        score_fn=score_fn,
        min_severity=min_severity,
        clock=clock,
        degraded=degraded,
    )
