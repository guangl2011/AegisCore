"""Latency instrumentation for SCAL translation.

Translation itself is pure; wall-clock timing is a side effect and lives at
the edge. ``InstrumentedTranslator`` wraps a ``SCALTranslator``, records one
``LatencySample`` per command via an injectable monotonic clock, and folds
the samples into a ``LatencyReport`` (p50/p99/max) that the bench harness
gates against the <5 ms Phase I target.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from aegiscore.core.model import TaskCommand
from aegiscore.scal.profiles import ScalProfile
from aegiscore.scal.translator import ChassisCommand, Pose2D, SCALTranslator

#: Monotonic clock returning integer nanoseconds.
Clock = Callable[[], int]


@dataclass(frozen=True)
class LatencySample:
    """Per-command translation latency."""

    primitive: str
    profile_model: str
    duration_ns: int


@dataclass(frozen=True)
class LatencyReport:
    """Summary of recorded translation latencies."""

    count: int
    mean_ns: float
    min_ns: int
    p50_ns: int
    p99_ns: int
    max_ns: int


def _percentile(sorted_values: list[int], fraction: float) -> int:
    """Nearest-rank percentile of an ascending list."""
    rank = math.ceil(fraction * len(sorted_values))
    return sorted_values[max(rank - 1, 0)]


class LatencyRecorder:
    """Accumulates latency samples and folds them into a report."""

    def __init__(self) -> None:
        self._samples: list[LatencySample] = []

    @property
    def samples(self) -> tuple[LatencySample, ...]:
        return tuple(self._samples)

    def record(self, sample: LatencySample) -> None:
        self._samples.append(sample)

    def report(self) -> LatencyReport:
        if not self._samples:
            raise ValueError(
                "no latency samples recorded; a report over an empty run is meaningless"
            )
        durations = sorted(sample.duration_ns for sample in self._samples)
        count = len(durations)
        return LatencyReport(
            count=count,
            mean_ns=sum(durations) / count,
            min_ns=durations[0],
            p50_ns=_percentile(durations, 0.50),
            p99_ns=_percentile(durations, 0.99),
            max_ns=durations[-1],
        )

    def reset(self) -> None:
        self._samples.clear()


class InstrumentedTranslator:
    """Wraps a ``SCALTranslator`` and records per-command translation latency."""

    def __init__(
        self,
        translator: SCALTranslator | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._translator = translator if translator is not None else SCALTranslator()
        self._clock: Clock = clock if clock is not None else time.perf_counter_ns
        self.recorder = LatencyRecorder()

    def translate(
        self,
        cmd: TaskCommand,
        profile: ScalProfile,
        context: Pose2D | None = None,
    ) -> list[ChassisCommand]:
        start = self._clock()
        result = self._translator.translate(cmd, profile, context)
        self.recorder.record(
            LatencySample(
                primitive=cmd.primitive,
                profile_model=profile.model,
                duration_ns=self._clock() - start,
            )
        )
        return result

    def translate_twist(
        self,
        profile: ScalProfile,
        v: float,
        omega: float,
        *,
        source: str = "Twist",
        issued_us: int = 0,
        duration_us: int = 0,
    ) -> ChassisCommand:
        start = self._clock()
        result = self._translator.translate_twist(
            profile, v, omega, source=source, issued_us=issued_us, duration_us=duration_us
        )
        self.recorder.record(
            LatencySample(
                primitive="Twist",
                profile_model=profile.model,
                duration_ns=self._clock() - start,
            )
        )
        return result

    def report(self) -> LatencyReport:
        return self.recorder.report()
