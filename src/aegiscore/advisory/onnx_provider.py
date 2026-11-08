"""onnxruntime fallback advisory provider — the non-Intel / no-OpenVINO seam.

Same :class:`AdvisoryProvider` interface as the OpenVINO backend, served by an
ONNX model through onnxruntime. physicalai itself registers an onnx adapter
alongside its OpenVINO adapter for exactly this portability reason; AegisCore
mirrors the seam so models can move between runtimes without touching the
governor-facing contract (locked decision: model choice behind an AegisCore
interface with an ONNX-runtime fallback).

Importing this module never imports onnxruntime — the import happens inside
:func:`create_onnx_provider`, so the advisory test suite runs in CI with stub
sessions only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from aegiscore.advisory.constraints import AdvisoryKind
from aegiscore.advisory.provider import ScoringAdvisoryProvider, scalar_score

ObsFn = Callable[[Any], Any]
ReadFrame = Callable[[], Any]


@runtime_checkable
class OnnxSessionLike(Protocol):
    """Structural view of the documented ``onnxruntime.InferenceSession``."""

    def run(
        self, output_names: list[str] | None, input_feed: dict[str, Any]
    ) -> list[Any]: ...

    def close(self) -> None: ...


class OnnxRuntimeAdvisoryProvider(ScoringAdvisoryProvider):
    """Advisory scoring through an ``onnxruntime.InferenceSession``.

    The ONNX model must reduce to a single scalar risk score per observation
    (``scalar_score`` unwraps a single-output tensor list, then the element).
    """

    def __init__(
        self,
        *,
        session: OnnxSessionLike,
        input_name: str,
        obs_fn: ObsFn | None = None,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(**base_kwargs)
        self._session = session
        self._input_name = input_name
        self._obs_fn = obs_fn

    def _score(self, frame_data: Any) -> float:
        observation = frame_data if self._obs_fn is None else self._obs_fn(frame_data)
        outputs = self._session.run(None, {self._input_name: observation})
        return scalar_score(outputs)

    def _on_close(self) -> None:
        self._session.close()


def create_onnx_provider(
    *,
    model_path: str,
    kind: AdvisoryKind | str,
    model_ref: str,
    read_frame: ReadFrame,
    input_name: str | None = None,
    providers: Sequence[str] | None = None,
    obs_fn: ObsFn | None = None,
    score_fn: Any = None,
    min_severity: float = 0.0,
    clock: Any = None,
) -> OnnxRuntimeAdvisoryProvider:
    """Build an onnxruntime-backed provider against a live onnxruntime install.

    Device degrade (silent): onnxruntime substitutes an unavailable execution
    provider (e.g. CUDA without drivers) with CPU — sometimes with no error at
    all. We read the actual provider back from the session and record
    ``degraded=True`` when it differs from the request; if the runtime raises
    instead (version-dependent), we retry on CPU the same way the OpenVINO
    factory does. ``ImportError`` (onnxruntime not installed) propagates for
    ``select_provider`` to turn into the null provider.
    """
    import onnxruntime as ort  # public documented API

    requested = list(providers) if providers is not None else ["CPUExecutionProvider"]
    degraded = False
    try:
        session = ort.InferenceSession(model_path, providers=requested)
    except RuntimeError:
        # Version-dependent behavior: some runtimes raise instead of silently
        # substituting. Retry on CPU and record the degrade.
        requested = ["CPUExecutionProvider"]
        session = ort.InferenceSession(model_path, providers=requested)
        degraded = True

    available = session.get_providers() or ["CPUExecutionProvider"]
    actual = available[0]
    input_name = input_name if input_name is not None else session.get_inputs()[0].name

    return OnnxRuntimeAdvisoryProvider(
        session=session,
        input_name=input_name,
        obs_fn=obs_fn,
        kind=kind,
        model_ref=model_ref,
        read_frame=read_frame,
        device=actual,
        score_fn=score_fn,
        min_severity=min_severity,
        clock=clock,
        # Degraded when the runtime substituted providers (CPU showing up
        # where an accelerator was requested) or we had to retry on CPU.
        degraded=degraded or not set(requested).issubset(set(available)),
    )
