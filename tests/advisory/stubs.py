"""Stub backends for the advisory suite — CI never installs physicalai/onnxruntime.

These mimic exactly the public surfaces the providers integrate against:
physicalai's ``Frame`` dataclass shape and the documented ``InferenceModel``
lifecycle (``select_action``/``close``). Fake import-modules for the factories
live in ``test_fallback.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Reviewed-SHA-shaped reference reused across the suite.
FULL_SHA = "a" * 40
MODEL_REF = f"OpenVINO/advisory-model@{FULL_SHA}"


@dataclass
class StubFrame:
    """Frame-like: physicalai.capture.Frame is (data, timestamp, sequence)."""

    data: Any
    timestamp: float = 0.0
    sequence: int = 0


class FakeArray:
    """Minimal ndarray stand-in: ``.size`` and ``.item()``, no numpy import."""

    def __init__(self, value: float, size: int = 1) -> None:
        self._value = value
        self.size = size

    def item(self) -> float:
        if self.size != 1:
            msg = "can only convert an array of size 1 to a Python scalar"
            raise ValueError(msg)
        return self._value


class StubModel:
    """``select_action``-shaped model returning a canned score (or raising)."""

    def __init__(self, score: Any = None, error: Exception | None = None) -> None:
        self.score = score
        self.error = error
        self.observations: list[Any] = []
        self.closed = False

    def select_action(self, observation: Any) -> Any:
        self.observations.append(observation)
        if self.error is not None:
            raise self.error
        return self.score

    def close(self) -> None:
        self.closed = True


class StubCamera:
    """physicalai Camera stand-in exposing the documented ``read_latest()``."""

    def __init__(self, frame: StubFrame | None = None) -> None:
        self.latest = frame if frame is not None else StubFrame(data="camera-frame")

    def read_latest(self) -> StubFrame:
        return self.latest
