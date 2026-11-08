"""AdvisoryProvider interface, the shared scoring core, and the null provider.

An advisory provider is a poll-only source of :class:`AdvisoryConstraint`
values. It has no API that produces, modifies, or carries an actuator
command — that is the layer's core safety property, not an accident of
implementation.

Degrade philosophy (spec: the advisory layer is optional, so it must never
block or crash the operational loop):

1. Requested NPU/GPU unavailable → silent degrade to CPU inside the backend
   factories (``create_openvino_provider``), recorded on ``degraded``.
2. physicalai/OpenVINO absent (``ImportError``) → onnxruntime provider
   (``select_provider``).
3. onnxruntime absent too → :class:`NullAdvisoryProvider` — advisory off,
   command path unaffected.

Errors met while *producing* a constraint (frame read failure, inference
fault, malformed model output) are recorded on the provider — ``last_error``,
``error_count`` — and yield no constraint for that poll. That is deliberate
isolation, not suppression: a missing advisory signal is a gap the governor
already tolerates (advisory is optional), while a crashing perception layer
would take the operational loop down with it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from math import isfinite
from time import monotonic_ns
from typing import Any, Protocol, runtime_checkable

from aegiscore.advisory.constraints import (
    AdvisoryConstraint,
    AdvisoryKind,
    validate_source_model,
)

Clock = Callable[[], int]
ReadFrame = Callable[[], Any]
ScoreFn = Callable[[Any], float]


@runtime_checkable
class AdvisoryProvider(Protocol):
    """What every advisory backend exposes. Poll-only, command-free.

    ``device`` is the resolved inference device (``"NPU"``, ``"CPU"``,
    ``"none"`` after full fallback); ``degraded`` is True when a fallback was
    applied (e.g. requested device unavailable, or a runtime swap).
    """

    @property
    def device(self) -> str: ...

    @property
    def degraded(self) -> bool: ...

    def poll(self) -> tuple[AdvisoryConstraint, ...]: ...

    def close(self) -> None: ...


def scalar_score(value: Any) -> float:
    """Extract one float risk score from a model output.

    Accepts a plain number, a numpy scalar or size-1 numpy array (unwrapped
    via ``item()``), or a dict/list/tuple holding a single value. Anything
    else is a contract error — the exported advisory model must produce one
    score.
    """
    if isinstance(value, Mapping):
        if len(value) != 1:
            msg = f"expected exactly one model output, got {len(value)} keys"
            raise ValueError(msg)
        value = next(iter(value.values()))
    elif isinstance(value, (list, tuple)):
        if len(value) != 1:
            msg = f"expected exactly one model output, got {len(value)}"
            raise ValueError(msg)
        value = value[0]
    item_method = getattr(value, "item", None)
    size = getattr(value, "size", None)
    if item_method is not None and size is not None:
        # numpy-style array: insist on exactly one element before unwrapping.
        if size != 1:
            msg = f"expected exactly one model output element, got {size}"
            raise ValueError(msg)
        value = item_method()
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        msg = f"model output is not reducible to a float score: {value!r}"
        raise ValueError(msg) from exc
    if not isfinite(score):
        msg = f"model output is not finite: {score}"
        raise ValueError(msg)
    return score


def severity_from_score(raw: float, *, min_severity: float = 0.0) -> float | None:
    """Map a raw model score to a constraint severity; ``None`` means no signal.

    Non-finite scores produce no constraint (a broken reading is the absence
    of advisory input, not a maximum-risk reading). Otherwise the score is
    clamped to [0, 1] and dropped when below ``min_severity``.
    """
    if not isfinite(raw):
        return None
    severity = min(1.0, max(0.0, raw))
    if severity < min_severity:
        return None
    return severity


class NullAdvisoryProvider:
    """Advisory disabled: publishes nothing, owns nothing, blocks nothing.

    The end of the fallback chain — when no inference runtime is installed,
    the advisory layer is simply absent and the deterministic cores run
    exactly as they would without it.
    """

    device = "none"
    degraded = False

    def poll(self) -> tuple[AdvisoryConstraint, ...]:
        return ()

    def close(self) -> None:
        return None


class ScoringAdvisoryProvider(ABC):
    """Shared poll machinery for inference-backed providers.

    Subclasses implement :meth:`_score` (one model inference on the frame's
    data) and optionally override :meth:`_on_close` to release the backend.
    """

    def __init__(
        self,
        *,
        kind: AdvisoryKind | str,
        model_ref: str,
        read_frame: ReadFrame,
        device: str,
        clock: Clock | None = None,
        score_fn: ScoreFn | None = None,
        min_severity: float = 0.0,
        degraded: bool = False,
    ) -> None:
        if not 0.0 <= min_severity <= 1.0:
            msg = f"min_severity must be in [0, 1], got {min_severity}"
            raise ValueError(msg)
        # Fail fast on a misconfigured provider instead of recording an error
        # on every poll forever.
        if not isinstance(kind, AdvisoryKind):
            try:
                kind = AdvisoryKind(kind)
            except ValueError as exc:
                allowed = [k.value for k in AdvisoryKind]
                msg = f"kind must be one of {allowed}, got {kind!r}"
                raise ValueError(msg) from exc
        self._kind = kind
        self._model_ref = validate_source_model(model_ref)
        self._read_frame = read_frame
        self._clock: Clock = clock if clock is not None else monotonic_ns
        self._score_fn: ScoreFn = score_fn if score_fn is not None else scalar_score
        self._min_severity = min_severity
        self.device = device
        self.degraded = degraded
        self.last_error: str | None = None
        self.error_count = 0

    @abstractmethod
    def _score(self, frame_data: Any) -> float:
        """Run one inference on the frame data and return a raw score."""

    def poll(self) -> tuple[AdvisoryConstraint, ...]:
        """One advisory cycle: read a frame, infer, score, stamp, emit.

        Isolation boundary (see module docstring): any failure here is
        recorded and yields no constraint — it never propagates into the
        operational loop.
        """
        try:
            frame = self._read_frame()
            if frame is None:
                return ()
            severity = severity_from_score(
                self._score_fn(self._score(frame.data)),
                min_severity=self._min_severity,
            )
            if severity is None:
                return ()
        except Exception as exc:  # noqa: BLE001 — deliberate isolation, documented
            self.error_count += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return ()
        return (
            AdvisoryConstraint(
                kind=self._kind,
                severity=severity,
                source_model=self._model_ref,
                issued_monotonic_ns=self._clock(),
            ),
        )

    def close(self) -> None:
        self._on_close()

    def _on_close(self) -> None:
        return None
