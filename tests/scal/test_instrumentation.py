"""Instrumentation tests: sample capture, report math, equivalence to the raw translator."""

import pytest

from aegiscore.core.model import TaskCommand
from aegiscore.scal.instrumentation import InstrumentedTranslator, LatencyRecorder, LatencySample
from aegiscore.scal.profiles import REFERENCE_PROFILES
from aegiscore.scal.translator import PRIMITIVE_MOVE_TO, Pose2D, SCALTranslator


class FakeClock:
    """Deterministic clock: yields a fixed list of nanosecond readings."""

    def __init__(self, readings: list[int]) -> None:
        self.readings = list(readings)

    def __call__(self) -> int:
        if not self.readings:
            raise AssertionError("fake clock exhausted")
        return self.readings.pop(0)


def test_recorder_report_percentiles() -> None:
    recorder = LatencyRecorder()
    for duration in range(1, 101):  # 1..100 ns
        recorder.record(LatencySample(primitive="X", profile_model="m", duration_ns=duration))
    report = recorder.report()
    assert report.count == 100
    assert report.min_ns == 1
    assert report.max_ns == 100
    assert report.mean_ns == 50.5
    # Nearest-rank: p50 of 1..100 is the 50th value; p99 is the 99th.
    assert report.p50_ns == 50
    assert report.p99_ns == 99


def test_recorder_report_on_empty_is_an_error() -> None:
    with pytest.raises(ValueError, match="no latency samples"):
        LatencyRecorder().report()


def test_translate_records_one_sample_per_command() -> None:
    clock = FakeClock([10, 60, 100, 143])  # durations: 50 ns and 43 ns
    instrumented = InstrumentedTranslator(clock=clock)
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    cmd = TaskCommand(
        primitive=PRIMITIVE_MOVE_TO, params={"x": 1.0, "y": 0.0, "theta": 0.0}, issued_us=0
    )

    instrumented.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
    instrumented.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))

    samples = instrumented.recorder.samples
    assert len(samples) == 2
    assert [s.duration_ns for s in samples] == [50, 43]
    assert all(s.primitive == PRIMITIVE_MOVE_TO for s in samples)
    assert all(s.profile_model == "ref-diff-mower" for s in samples)


def test_translate_twist_is_recorded_too() -> None:
    clock = FakeClock([5, 12])
    instrumented = InstrumentedTranslator(clock=clock)
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    instrumented.translate_twist(profile, 0.4, 0.0)
    assert [s.duration_ns for s in instrumented.recorder.samples] == [7]
    assert instrumented.recorder.samples[0].primitive == "Twist"


def test_instrumented_translator_matches_raw_translator() -> None:
    profile = REFERENCE_PROFILES["ref-ack-utv"]
    cmd = TaskCommand(
        primitive=PRIMITIVE_MOVE_TO, params={"x": 3.0, "y": 1.0, "theta": 0.0}, issued_us=0
    )
    instrumented = InstrumentedTranslator(clock=lambda: 0)
    raw = SCALTranslator()
    assert instrumented.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0)) == raw.translate(
        cmd, profile, Pose2D(0.0, 0.0, 0.0)
    )


def test_instrumented_translator_wraps_custom_translator() -> None:
    custom = SCALTranslator()
    instrumented = InstrumentedTranslator(translator=custom, clock=lambda: 0)
    assert instrumented._translator is custom


def test_report_after_real_clock_smoke() -> None:
    """With the real clock, every translation yields a non-negative sample."""
    instrumented = InstrumentedTranslator()
    for profile in REFERENCE_PROFILES.values():
        cmd = TaskCommand(
            primitive=PRIMITIVE_MOVE_TO, params={"x": 3.0, "y": 0.5, "theta": 0.1}, issued_us=0
        )
        instrumented.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
    report = instrumented.report()
    assert report.count == 3
    assert report.min_ns >= 0
    assert report.p99_ns >= report.p50_ns >= report.min_ns
    assert report.max_ns >= report.p99_ns


def test_reset_clears_samples() -> None:
    instrumented = InstrumentedTranslator(clock=lambda: 0)
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    cmd = TaskCommand(
        primitive=PRIMITIVE_MOVE_TO, params={"x": 1.0, "y": 0.0, "theta": 0.0}, issued_us=0
    )
    instrumented.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
    instrumented.recorder.reset()
    assert instrumented.recorder.samples == ()
