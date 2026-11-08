"""Advisory-experiment tests: metrics emission, schema validity, determinism,
and the advisory evidence gate — including the seeded red-gate demonstration
the testing-plan discipline requires before the new gate is trusted green.

Slice runs (3 trajectories + the 24-scenario fault matrix) keep these fast;
the full-run advisory block is asserted against the shared module fixture in
``test_harness.py``.
"""

from __future__ import annotations

import json

import pytest

from aegiscore.harness import (
    AdvisoryExperimentConfig,
    AdvisoryWiring,
    BenchConfig,
    evaluate_gates,
    gate_report,
    metrics_to_json,
    run_benchmark,
    run_nominal_trajectory,
)
from aegiscore.scal.corpus import CORPUS_SEED, build_corpus
from aegiscore.scal.instrumentation import InstrumentedTranslator
from aegiscore.scal.profiles import REFERENCE_PROFILES

#: Deterministic clock for byte-stable metrics (every sample 0 ns).
DET_CLOCK = lambda: 0  # noqa: E731

SLICE = BenchConfig(corpus_size=3, clock=DET_CLOCK)


@pytest.fixture(scope="module")
def slice_metrics():
    return run_benchmark(SLICE)


def _assert_latency_shape(report: dict) -> None:
    assert report["count"] > 0
    assert 0 <= report["min_ns"] <= report["p50_ns"] <= report["p99_ns"] <= report["max_ns"]
    assert report["min_ns"] <= report["mean_ns"] <= report["max_ns"]


# ------------------------------------------------------------- emission/shape


def test_advisory_block_is_emitted_and_schema_valid(slice_metrics) -> None:
    adv = slice_metrics.advisory
    assert adv is not None
    doc = adv.to_dict()
    assert set(doc) == {
        "provider",
        "polls",
        "constraints_offered",
        "accepted",
        "rejected_stale",
        "descent_coverage",
        "issuance_latency_ns",
        "consumption_latency_ns",
    }
    assert doc["provider"] == {"device": "stub", "degraded": False}
    assert doc["polls"] > 0
    # Intake bookkeeping balances: every offer was accepted or refused.
    assert doc["constraints_offered"] == doc["accepted"] + doc["rejected_stale"]
    # One issuance sample per poll, one consumption sample per offer.
    _assert_latency_shape(doc["issuance_latency_ns"])
    assert doc["issuance_latency_ns"]["count"] == doc["polls"]
    _assert_latency_shape(doc["consumption_latency_ns"])
    assert doc["consumption_latency_ns"]["count"] == doc["constraints_offered"]


def test_descent_coverage_counts_only_advisory_reasons(slice_metrics) -> None:
    adv = slice_metrics.advisory
    coverage = adv.to_dict()["descent_coverage"]
    assert coverage["governor_cycles"] > 0
    assert coverage["advisory_descents"] > 0
    # Every counted descent names a ladder rung, and the per-rung breakdown
    # sums to the total. The current governor contract targets FILTERED for
    # advisory inputs (fault classes outrank them); CONSERVATIVE appears here
    # so a future change that routes advisory descents deeper stays honest.
    assert set(coverage["by_target_mode"]) <= {"FILTERED", "CONSERVATIVE"}
    assert sum(coverage["by_target_mode"].values()) == coverage["advisory_descents"]
    assert coverage["descents_per_10k_cycles"] == pytest.approx(
        coverage["advisory_descents"] * 10_000.0 / coverage["governor_cycles"]
    )
    assert adv.advisory_descents == coverage["advisory_descents"]


def test_staleness_rejections_are_measured(slice_metrics) -> None:
    adv = slice_metrics.advisory
    # The stub schedules stale offers on a cadence, but acceptance stays
    # measured: a stale-window poll landing inside a run's first freshness
    # window (100 ms of sim time) is genuinely fresh and accepted. Either
    # way the freshness gate must have refused the bulk of them.
    assert adv.rejected_stale > 0
    assert adv.rejected_stale > adv.accepted * 0.1


# ---------------------------------------------------- JSON document + determinism


def test_advisory_block_joins_the_evidence_json(slice_metrics) -> None:
    doc = json.loads(metrics_to_json(slice_metrics))
    assert doc["schema_version"] == 2
    assert doc["advisory"]["provider"]["device"] == "stub"
    assert doc["gates"]["advisory_descents_observed"] is True
    assert doc["gates"]["all_pass"] is True


def test_advisory_metrics_deterministic_across_seeded_runs() -> None:
    first = run_benchmark(SLICE).advisory.to_dict()
    second = run_benchmark(SLICE).advisory.to_dict()
    assert first == second


# ------------------------------------------------------------ pipeline invariant


def test_advisory_pass_never_breaks_the_command_path_invariants() -> None:
    corpus = build_corpus(CORPUS_SEED, 1)
    traj = corpus[0]
    profile = REFERENCE_PROFILES[traj.profile_name]
    wiring = AdvisoryWiring(AdvisoryExperimentConfig())
    result = run_nominal_trajectory(
        traj, profile, translator=InstrumentedTranslator(clock=DET_CLOCK), advisory=wiring
    )
    # The advisory wiring observes every cycle (one before_cycle per step) and
    # changes nothing about the pipeline's guarantees.
    assert wiring.cycles == result.steps
    assert result.violations == ()
    assert result.logged_records == result.steps
    assert wiring.descents > 0  # the pass actually exercised the descent path


# ---------------------------------------------------------------- gate checks


def _green_base() -> dict:
    return {
        "p99_translation_ns": 0,
        "max_transition_latency_us": 0.0,
        "kinematic_violation_count": 0,
        "decision_logging_completeness": 1.0,
        "scenarios_in_defined_safe_state": 1,
        "scenario_count": 1,
    }


def test_gate_evaluation_advisory_descents() -> None:
    # Disabled pass (None): the gate is not evaluated and cannot fail the run.
    assert evaluate_gates(**_green_base(), advisory_descents=None).passed
    # Enabled pass with zero descents: the advisory path never drove the
    # governor — exactly what the gate exists to catch.
    report = evaluate_gates(**_green_base(), advisory_descents=0)
    assert not report.passed
    assert report.failures == ("advisory_descents_observed",)
    assert evaluate_gates(**_green_base(), advisory_descents=3).passed


def test_zero_descent_schedule_turns_gate_red_then_reverts() -> None:
    # A schedule that never emits severity 1.0 (zero remaining margin) can
    # never drive a descent — the deterministic red demonstration.
    quiet = run_benchmark(
        BenchConfig(
            corpus_size=3,
            clock=DET_CLOCK,
            advisory=AdvisoryExperimentConfig(zero_margin_rate=0.0),
        )
    )
    assert quiet.advisory is not None
    assert quiet.advisory.advisory_descents == 0
    assert quiet.advisory.constraints_offered > 0  # offers happened, none bit
    report = gate_report(quiet)
    assert not report.passed
    assert "advisory_descents_observed" in report.failures

    # The default schedule restores a green run.
    clean = run_benchmark(SLICE)
    assert gate_report(clean).passed
