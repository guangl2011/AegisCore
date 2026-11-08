"""Bench harness tests: the SCAL->governor bridge, corpus runs, the fault
matrix, and the CI evidence gates — including the seeded red-gate evidence
the testing plan requires before the gates are trusted green.

Full-benchmark tests (determinism, runtime budget, gates-green) each run the
real 100-trajectory corpus + 24-scenario fault matrix; together they keep the
suite a few minutes. Gate-red demonstrations run a 3-trajectory slice (one per
chassis) to stay fast.
"""

from __future__ import annotations

import time

import pytest

from aegiscore.core.model import ActuatorCommand, GovernorDecision, GovMode
from aegiscore.governor import Fault
from aegiscore.governor.fsm import LADDER
from aegiscore.harness import (
    FAIL_SAFE_LIMIT_US,
    P99_TRANSLATION_LIMIT_NS,
    RUNTIME_BUDGET_S,
    BenchConfig,
    BreachSeed,
    run_benchmark,
    run_fault_matrix,
    run_nominal_trajectory,
)
from aegiscore.harness.metrics import gate_report, metrics_to_json
from aegiscore.harness.runner import ElementPlan, element_plan, executed_twist
from aegiscore.scal.corpus import CORPUS_SEED, build_corpus
from aegiscore.scal.instrumentation import InstrumentedTranslator
from aegiscore.scal.kinematics import TwistSolution, forward_twist
from aegiscore.scal.profiles import REFERENCE_PROFILES
from aegiscore.scal.translator import Pose2D, SCALTranslator
from aegiscore.sim import SIM_DT_US

#: Deterministic clock for byte-stable metrics (every sample 0 ns).
DET_CLOCK = lambda: 0  # noqa: E731

ALL_PROFILES = list(REFERENCE_PROFILES.values())
SLICE = BenchConfig(corpus_size=3, clock=DET_CLOCK)

# Exact fault-walk depths in governor cycles (chassis-independent) — the
# deterministic fail-safe ladder descent, so each fault class's transition
# latency is its walk depth in simulation time.
WALK_CYCLES: dict[Fault, int] = {
    Fault.SPOOFED_COMMAND: 3,  # -> CONTROLLED_STOP
    Fault.STALE_HEARTBEAT: 2,  # -> HOLD
    Fault.SENSOR_LOSS: 2,  # -> HOLD
    Fault.NETWORK_LOSS: 3,  # -> CONTROLLED_STOP
    Fault.WATCHDOG_MISS: 3,  # -> CONTROLLED_STOP
    Fault.BRAKING_LOSS: 0,  # E_STOP fires in the onset cycle
    Fault.PROXIMITY_E_STOP: 0,  # E_STOP fires in the onset cycle
    Fault.UNMODELED: 3,  # -> CONTROLLED_STOP
}


def _admitted(value: float) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id="act.drive", command_type="drive_speed", value=value, issued_us=0
    )


def _at_or_below(mode: GovMode, target_value: str) -> bool:
    target = GovMode(target_value)
    return LADDER.index(mode) >= LADDER.index(target)


def _first_corpus_elements(profile_name: str, primitive: str):
    """Translate the first matching corpus command across the profile's missions."""
    return _first_corpus_elements_matching(profile_name, primitive, lambda _els: True)


def _first_corpus_elements_matching(profile_name: str, primitive: str, predicate):
    """Translate the first corpus command matching primitive and element predicate."""
    profile = REFERENCE_PROFILES[profile_name]
    translator = SCALTranslator()
    for traj in build_corpus(CORPUS_SEED, 100):
        if traj.profile_name != profile_name:
            continue
        for cmd in traj.commands:
            if cmd.primitive != primitive:
                continue
            elements = translator.translate(cmd, profile, Pose2D())
            if predicate(elements):
                return profile, elements
    raise AssertionError(f"no {primitive} command matching the predicate for {profile_name}")


# --------------------------------------------------------------- SCAL bridge


def test_element_plan_exposes_forward_twist_of_wheel_targets() -> None:
    profile, elements = _first_corpus_elements("ref-diff-mower", "MoveTo")
    motion = [
        e for e in elements if any(t.command_type == "wheel_speed" for t in e.targets.values())
    ]
    assert motion, "expected wheel-target elements in a MoveTo stream"
    element = motion[0]
    plan = element_plan(element, profile, SIM_DT_US)
    solution = TwistSolution(
        wheel_speeds={
            role: t.value for role, t in element.targets.items() if t.command_type == "wheel_speed"
        },
        steering_angles={},
    )
    expected_v, expected_omega = forward_twist(profile, solution)
    assert plan.is_motion
    assert plan.v_mps == pytest.approx(expected_v)
    assert plan.omega_rad_s == pytest.approx(expected_omega)
    assert plan.n_cycles == max(1, round(element.duration_us / SIM_DT_US))


def test_element_plan_marks_in_place_rotations() -> None:
    profile, elements = _first_corpus_elements("ref-diff-mower", "MoveTo")
    rotations = [element_plan(e, profile, SIM_DT_US) for e in elements]
    assert any(p.is_rotation for p in rotations), "expected a rotate-in element"
    rotation = next(p for p in rotations if p.is_rotation)
    assert rotation.v_mps == pytest.approx(0.0)
    assert abs(rotation.omega_rad_s) > 0.0
    assert rotation.kappa_inv_m == 0.0


def test_element_plan_blade_elements_are_not_motion() -> None:
    # The corpus samples blade enable and disable; find a mission command that
    # spins the blade up and check its plan shape.
    profile, elements = _first_corpus_elements_matching(
        "ref-diff-mower",
        "SetBlade",
        lambda els: any(
            t.command_type == "blade_on" for el in els for t in el.targets.values()
        ),
    )
    assert len(elements) == 1
    plan = element_plan(elements[0], profile, SIM_DT_US)
    assert not plan.is_motion
    assert plan.blade_on is True
    assert plan.blade_speed_rad_s > 0.0
    # Dock streams append blade-off elements; those plans stay non-motion too.
    _, dock_elements = _first_corpus_elements("ref-diff-mower", "Dock")
    dock_plans = [element_plan(e, profile, SIM_DT_US) for e in dock_elements]
    blade_off_plans = [p for p in dock_plans if not p.is_motion]
    assert blade_off_plans, "Dock appends a blade-off element for blade-fitted chassis"
    assert all(not p.blade_on for p in blade_off_plans)


def test_element_plan_ackermann_arcs_carry_consistent_curvature() -> None:
    # Ackermann chassis steer by arc: every element's curvature must satisfy
    # omega = kappa * v, and no Ackermann element may be an in-place spin.
    profile, elements = _first_corpus_elements("ref-ack-utv", "FollowPath")
    plans = [element_plan(e, profile, SIM_DT_US) for e in elements]
    assert plans
    assert all(not p.is_rotation for p in plans), "Ackermann cannot spin in place"
    for plan in plans:
        assert plan.is_motion
        assert plan.omega_rad_s == pytest.approx(plan.kappa_inv_m * plan.v_mps, rel=1e-9, abs=1e-12)
    assert any(p.kappa_inv_m != 0.0 for p in plans), "the corpus includes steering arcs"


def test_executed_twist_tracks_path_curvature_at_the_admitted_speed() -> None:
    plan = ElementPlan(
        source="FollowPath:seg0",
        n_cycles=10,
        is_motion=True,
        is_rotation=False,
        v_mps=1.0,
        omega_rad_s=0.2,
        kappa_inv_m=0.2,  # omega / v
        primitive="FollowPath",
    )
    decision = GovernorDecision(
        admitted=_admitted(0.5), mode=GovMode.NOMINAL, margins={}, reason=None
    )
    v, omega = executed_twist(plan, decision)
    assert v == pytest.approx(0.5)
    assert omega == pytest.approx(0.1)  # same path, half speed


def test_executed_twist_halts_rotation_when_filtered() -> None:
    plan = ElementPlan(
        source="MoveTo:rotate_in",
        n_cycles=10,
        is_motion=True,
        is_rotation=True,
        v_mps=0.0,
        omega_rad_s=0.5,
        kappa_inv_m=0.0,
        primitive="MoveTo",
    )
    spinning = GovernorDecision(
        admitted=_admitted(0.0), mode=GovMode.NOMINAL, margins={}, reason=None
    )
    halted = GovernorDecision(
        admitted=_admitted(0.0),
        mode=GovMode.CONTROLLED_STOP,
        margins={},
        reason="controlled_stop",
    )
    assert executed_twist(plan, spinning)[1] == pytest.approx(0.5)
    assert executed_twist(plan, halted) == (0.0, 0.0)


def test_executed_twist_no_admission_means_no_actuation() -> None:
    plan = ElementPlan(
        source="MoveTo",
        n_cycles=5,
        is_motion=True,
        is_rotation=False,
        v_mps=1.0,
        omega_rad_s=0.0,
        kappa_inv_m=0.0,
        primitive="MoveTo",
    )
    decision = GovernorDecision(admitted=None, mode=GovMode.E_STOP, margins={}, reason="e_stop")
    assert executed_twist(plan, decision) == (0.0, 0.0)


# ------------------------------------------------------- nominal corpus runs


def test_nominal_trajectory_is_fully_logged_and_unviolated() -> None:
    profile = REFERENCE_PROFILES["ref-hybrid-mower"]
    traj = next(t for t in build_corpus(CORPUS_SEED, 6) if t.profile_name == profile.model)
    result = run_nominal_trajectory(
        traj, profile, translator=InstrumentedTranslator(clock=DET_CLOCK)
    )
    assert result.steps > 0
    assert result.logged_records == result.steps
    assert result.violations == ()
    assert result.transitions == 0  # nominal missions never leave NOMINAL


def test_nominal_runs_across_all_three_chassis() -> None:
    corpus = build_corpus(CORPUS_SEED, 3)
    translator = InstrumentedTranslator(clock=DET_CLOCK)
    models = set()
    for traj in corpus:
        profile = REFERENCE_PROFILES[traj.profile_name]
        result = run_nominal_trajectory(traj, profile, translator=translator)
        assert result.violations == (), (traj.trajectory_id, result.violations)
        assert result.logged_records == result.steps
        models.add(profile.model)
    assert models == set(REFERENCE_PROFILES)


# --------------------------------------------------------------- fault matrix


@pytest.fixture(scope="module")
def slice_matrix():
    corpus = build_corpus(CORPUS_SEED, 3)
    return run_fault_matrix(corpus)


def test_fault_matrix_covers_every_class_on_every_chassis(slice_matrix) -> None:
    assert len(slice_matrix) == 3 * len(Fault)
    pairs = {(s.chassis, s.fault) for s in slice_matrix}
    expected = {(profile.model, fault.value) for profile in ALL_PROFILES for fault in Fault}
    assert pairs == expected


def test_fault_scenarios_reach_their_mapped_safe_state(slice_matrix) -> None:
    for record in slice_matrix:
        assert record.arrival_cycle >= 0, record
        assert record.in_defined_safe_state, record
        # The final mode sits at the mapped rung or deeper on the ladder
        # (e.g. sustained stale heartbeat holds until the hold timeout, then
        # descends to CONTROLLED_STOP).
        assert _at_or_below(GovMode(record.final_mode), record.mapped_safe_state), record


def test_fault_transition_latency_within_the_50ms_budget(slice_matrix) -> None:
    worst = max(slice_matrix, key=lambda s: s.transition_latency_us)
    assert worst.transition_latency_us <= FAIL_SAFE_LIMIT_US
    # Exact walk depths: the ladder descent is deterministic, so each class's
    # latency is its walk depth in simulation time.
    for record in slice_matrix:
        fault = Fault(record.fault)
        assert record.transition_latency_us == WALK_CYCLES[fault] * SIM_DT_US, record


def test_fault_scenarios_never_execute_inadmissible_twists(slice_matrix) -> None:
    for record in slice_matrix:
        assert record.kinematic_violations == 0, record
        assert record.logged_records == record.steps, record


def test_stale_heartbeat_arrives_at_hold_then_deepens(slice_matrix) -> None:
    # HOLD -> CONTROLLED_STOP after the hold timeout is expected under a
    # sustained stale heartbeat; the arrival bookkeeping must still show HOLD
    # was reached at the mapped walk depth, not jumped over.
    for record in slice_matrix:
        if record.fault == Fault.STALE_HEARTBEAT.value:
            assert record.arrival_cycle - record.onset_cycle == WALK_CYCLES[Fault.STALE_HEARTBEAT]
            assert record.final_mode == GovMode.CONTROLLED_STOP.value


# ----------------------------------------------------------- CI gate evidence


@pytest.fixture(scope="module")
def full_metrics():
    return run_benchmark(BenchConfig(clock=DET_CLOCK))


def test_full_benchmark_gates_green(full_metrics) -> None:
    report = gate_report(full_metrics)
    assert report.passed, report.failures
    assert full_metrics.corpus_trajectories == 100
    assert len(full_metrics.scenarios) == 24
    assert full_metrics.corpus_transitions == 0
    assert full_metrics.kinematic_violation_count == 0
    assert full_metrics.decision_logging_completeness == 1.0
    assert full_metrics.max_transition_latency_us <= FAIL_SAFE_LIMIT_US
    assert full_metrics.translation_latency_ns is not None
    assert full_metrics.translation_latency_ns.p99_ns < P99_TRANSLATION_LIMIT_NS


def test_full_benchmark_translation_latency_measured_per_chassis(full_metrics) -> None:
    by_chassis = full_metrics.translation_latency_by_chassis_ns
    assert set(by_chassis) == set(REFERENCE_PROFILES)
    for report in by_chassis.values():
        assert report.count > 0
        assert report.p99_ns < P99_TRANSLATION_LIMIT_NS


def test_full_benchmark_advisory_experiment_block(full_metrics) -> None:
    # The advisory pass rides the default configuration: the CI evidence run
    # always carries the block, and it must be green like the rest.
    adv = full_metrics.advisory
    assert adv is not None
    assert adv.polls > 0
    assert adv.constraints_offered == adv.accepted + adv.rejected_stale
    assert adv.advisory_descents > 0
    assert adv.rejected_stale > 0
    assert adv.issuance_latency_ns is not None
    assert adv.consumption_latency_ns is not None
    assert gate_report(full_metrics).passed


def test_harness_determinism_two_runs_byte_identical() -> None:
    first = metrics_to_json(run_benchmark(BenchConfig(clock=DET_CLOCK)))
    second = metrics_to_json(run_benchmark(BenchConfig(clock=DET_CLOCK)))
    assert first == second


def test_harness_runtime_budget_full_run() -> None:
    started = time.perf_counter()
    metrics = run_benchmark(BenchConfig(clock=DET_CLOCK))
    elapsed = time.perf_counter() - started
    assert elapsed < RUNTIME_BUDGET_S, (
        f"harness took {elapsed:.1f}s, budget {RUNTIME_BUDGET_S:.0f}s"
    )
    assert gate_report(metrics).passed


def test_seeded_breach_turns_gates_red_then_reverts() -> None:
    # A compromised host writes 5 m/s straight to the actuators on the first
    # corpus trajectory — the differential mower's envelope tops out at 1.5.
    breached = run_benchmark(
        BenchConfig(
            corpus_size=3,
            clock=DET_CLOCK,
            breach_seed=BreachSeed(speed_mps=5.0, trajectory_index=0),
        )
    )
    assert breached.kinematic_violation_count >= 1
    report = gate_report(breached)
    assert not report.passed
    assert "no_kinematic_violations" in report.failures

    # Reverting the breach restores a green run.
    clean = run_benchmark(SLICE)
    assert gate_report(clean).passed
    assert clean.kinematic_violation_count == 0


def test_late_transition_turns_gates_red_then_reverts() -> None:
    # A 20 ms supervisor cycle doubles the deterministic walk depth in time:
    # the 3-cycle CONTROLLED_STOP walk becomes 60 ms — over the 50 ms budget,
    # exactly the regression the fail-safe gate exists to catch.
    slow = run_benchmark(BenchConfig(corpus_size=3, clock=DET_CLOCK, sim_dt_us=20_000))
    worst = slow.max_transition_latency_us
    assert worst is not None and worst > FAIL_SAFE_LIMIT_US
    report = gate_report(slow)
    assert not report.passed
    assert "fail_safe_within_50ms" in report.failures

    # The default 10 ms cycle meets the budget.
    on_time = run_benchmark(SLICE)
    assert gate_report(on_time).passed
    assert on_time.max_transition_latency_us <= FAIL_SAFE_LIMIT_US
