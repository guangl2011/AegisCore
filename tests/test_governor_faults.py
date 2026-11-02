"""Fault-injection suite: six+ fault classes, <=50 ms fail-safe, defined safe states.

Phase I aim under test: a deterministic fail-safe transition within 50 ms of
fault injection, terminating in the safe state the spec table defines for the
class. The suite exercises each class through the injection channel and,
where inputs can express the fault naturally (NaN sensors, stale heartbeats,
spoofed command envelopes, dead brakes), through real inputs as well.
"""

from __future__ import annotations

import pytest

from aegiscore.core.model import GovMode
from aegiscore.governor import Fault

CYCLE_US = 1_000
SAFE_STATE_BUDGET_US = 50_000


def assert_latency_budget(gov) -> None:
    """Every logged cycle — and every logged transition — reports <=50 ms latency."""
    for record in gov.safety_log.records:
        assert record.latency_us <= SAFE_STATE_BUDGET_US, f"cycle {record.seq} latency"
        if record.transition_to is not None:
            assert record.transition_from is not None
            assert record.latency_us <= SAFE_STATE_BUDGET_US


def run_sustained(
    gov, make_state, make_cmd, *, fault=None, state_kwargs=None, cmd_fn=None, cycles=10
):
    """Step `cycles` identical fault-condition cycles; return every decision."""
    state_kwargs = state_kwargs or {}
    decisions = []
    for i in range(cycles):
        now = i * CYCLE_US
        cmd = cmd_fn(now) if cmd_fn is not None else make_cmd(issued_us=now)
        decisions.append(
            gov.step(make_state(now_us=now, **state_kwargs), cmd, now, fault=fault)
        )
    return decisions


def drive_to_safe_state(
    gov, make_state, make_cmd, *, fault, expected, state_kwargs=None, cmd_fn=None
):
    """Fault cycles from a fresh governor; return (arrival cycle, decision).

    Asserts the fault -> safe-state time stays within the 50 ms budget and that
    every logged transition latency does too.
    """
    state_kwargs = state_kwargs or {}
    for i in range(200):
        now = i * CYCLE_US
        cmd = cmd_fn(now) if cmd_fn is not None else make_cmd(issued_us=now)
        decision = gov.step(make_state(now_us=now, **state_kwargs), cmd, now, fault=fault)
        if decision.mode is expected:
            assert now <= SAFE_STATE_BUDGET_US, f"{fault} took {now} us to reach {expected}"
            assert_latency_budget(gov)
            return i, decision
    pytest.fail(f"{fault} never reached {expected}")


def assert_stop_output(decision) -> None:
    """The admitted command (if any) is a stop command, never task traffic."""
    if decision.admitted is None:
        return
    assert decision.admitted.command_type in ("drive_speed", "blade_off")
    if decision.admitted.command_type == "drive_speed":
        assert decision.admitted.value == 0.0


# ----------------------------------------------------------- spoofed commands


def test_spoofed_command_via_real_inputs_reaches_controlled_stop(
    make_governor, make_state, make_cmd
):
    """A command time-stamped in the future cannot come from a legitimate host."""
    gov = make_governor(network_loss_timeout_us=1_000_000)
    decisions = run_sustained(
        gov, make_state, make_cmd,
        cmd_fn=lambda now: make_cmd(target_speed=0.5, issued_us=now + 1_000_000),
        cycles=6,
    )
    arrival = next(d for d in decisions if d.mode is GovMode.CONTROLLED_STOP)
    idx = decisions.index(arrival)
    assert idx * CYCLE_US <= SAFE_STATE_BUDGET_US
    assert_latency_budget(gov)
    for d in decisions:
        assert_stop_output(d)  # no task traffic while the fault is present
    # defined safe state: at rest in CONTROLLED_STOP, awaiting operator re-arm
    assert arrival.reason == "spoof_suspected"
    assert gov.re_arm(False, idx * CYCLE_US) is False
    assert gov.mode is GovMode.CONTROLLED_STOP
    assert gov.re_arm(True, idx * CYCLE_US) is True
    assert gov.mode is GovMode.CONSERVATIVE


def test_spoofed_command_injection_matches_real_input_outcome(make_governor, make_state, make_cmd):
    gov = make_governor(network_loss_timeout_us=1_000_000)
    decisions = run_sustained(gov, make_state, make_cmd, fault=Fault.SPOOFED_COMMAND, cycles=6)
    assert any(d.mode is GovMode.CONTROLLED_STOP for d in decisions)
    assert_latency_budget(gov)


# ----------------------------------------------------------- stale heartbeat


def test_stale_heartbeat_loses_lease_to_hold_then_recovers(make_governor, make_state, make_cmd):
    gov = make_governor(
        heartbeat_lease_us=5_000,
        network_loss_timeout_us=1_000_000,
        hold_timeout_us=10_000_000,
        conservative_recovery_cycles=10_000,
    )
    decisions = run_sustained(
        gov, make_state, make_cmd,
        state_kwargs={"heartbeat_age_us": 6_000},
        cycles=4,
    )
    hold = next(d for d in decisions if d.mode is GovMode.HOLD)
    assert hold.reason == "heartbeat_lease_lost"
    assert decisions.index(hold) * CYCLE_US <= SAFE_STATE_BUDGET_US
    for d in decisions:
        assert_stop_output(d)  # HOLD: zero-velocity, actuators powered
    # table exit: lease restored -> CONSERVATIVE
    recovered = gov.step(make_state(now_us=4_000), make_cmd(issued_us=4_000), 4_000)
    assert recovered.mode is GovMode.CONSERVATIVE
    assert_latency_budget(gov)


def test_sustained_hold_times_out_to_controlled_stop(make_governor, make_state, make_cmd):
    gov = make_governor(
        heartbeat_lease_us=5_000,
        network_loss_timeout_us=1_000_000,
        hold_timeout_us=10_000,
    )
    decisions = run_sustained(
        gov, make_state, make_cmd,
        state_kwargs={"heartbeat_age_us": 6_000},
        cycles=16,
    )
    assert any(d.reason == "hold_timeout" for d in decisions)
    assert decisions[-1].mode is GovMode.CONTROLLED_STOP
    assert_latency_budget(gov)


# --------------------------------------------------------------- sensor loss


def test_sensor_loss_degrades_then_persists_to_hold(make_governor, make_state, make_cmd):
    gov = make_governor(
        sensor_loss_persistent_cycles=3,
        network_loss_timeout_us=1_000_000,
        conservative_recovery_cycles=10_000,
    )
    decisions = run_sustained(
        gov, make_state, make_cmd,
        state_kwargs={"v": float("nan")},
        cycles=5,
    )
    hold = next(d for d in decisions if d.mode is GovMode.HOLD)
    assert hold.reason.startswith("sensor_loss:")
    assert decisions.index(hold) * CYCLE_US <= SAFE_STATE_BUDGET_US
    modes = [d.mode for d in decisions]
    assert GovMode.NOMINAL not in modes  # degraded sensors never look nominal
    assert_latency_budget(gov)


def test_transient_sensor_loss_recovers(make_governor, make_state, make_cmd):
    gov = make_governor(sensor_loss_persistent_cycles=3, conservative_recovery_cycles=2)
    d0 = gov.step(make_state(now_us=0, v=float("nan")), make_cmd(issued_us=0), 0)
    assert d0.mode is GovMode.FILTERED  # one degraded cycle dips a single rung
    d1 = gov.step(make_state(now_us=1_000), make_cmd(issued_us=1_000), 1_000)
    assert d1.mode is GovMode.NOMINAL  # healthy unfiltered cycle: margins recovered
    d2 = gov.step(make_state(now_us=2_000), make_cmd(issued_us=2_000), 2_000)
    assert d2.mode is GovMode.NOMINAL


# -------------------------------------------------------------- network loss


def test_network_loss_reaches_controlled_stop(make_governor, make_state, make_cmd):
    gov = make_governor(network_loss_timeout_us=500_000, hold_timeout_us=10_000_000)
    decisions = run_sustained(
        gov, make_state, make_cmd,
        state_kwargs={"heartbeat_age_us": 600_000},
        cycles=6,
    )
    arrival = next(d for d in decisions if d.mode is GovMode.CONTROLLED_STOP)
    assert arrival.reason == "network_loss"
    assert decisions.index(arrival) * CYCLE_US <= SAFE_STATE_BUDGET_US
    for d in decisions:
        assert_stop_output(d)
    assert_latency_budget(gov)


# ------------------------------------------------------------- watchdog miss


def test_single_watchdog_gap_dips_one_rung_then_recovers(make_governor, make_state, make_cmd):
    """A single supervisor stall dips one rung; healthy cycles recover it (table
    exit). A sustained miss walks to CONTROLLED_STOP within budget — covered by
    test_watchdog_miss_injection and the fault matrix."""
    gov = make_governor()  # watchdog_timeout_us defaults to 20_000
    gov.step(make_state(now_us=0), make_cmd(issued_us=0), 0)
    d1 = gov.step(make_state(now_us=25_000), make_cmd(issued_us=25_000), 25_000)
    assert d1.reason == "watchdog_miss"
    assert d1.mode is GovMode.FILTERED  # walk begins: one rung this cycle
    d2 = gov.step(make_state(now_us=26_000), make_cmd(issued_us=26_000), 26_000)
    assert d2.mode is GovMode.NOMINAL  # transient miss: margins recovered


def test_watchdog_miss_injection(make_governor, make_state, make_cmd):
    gov = make_governor(network_loss_timeout_us=1_000_000)
    decisions = run_sustained(gov, make_state, make_cmd, fault=Fault.WATCHDOG_MISS, cycles=6)
    assert any(d.mode is GovMode.CONTROLLED_STOP for d in decisions)
    assert_latency_budget(gov)


# -------------------------------------------------------------- braking loss


def test_braking_loss_is_immediate_e_stop(make_governor, make_state, make_cmd):
    gov = make_governor()
    d0 = gov.step(make_state(now_us=0, brake=0.0), make_cmd(issued_us=0), 0)
    assert d0.mode is GovMode.E_STOP
    assert d0.reason == "braking_authority_lost"
    assert d0.admitted is None  # torque removal — the independent e-stop path
    assert 0 <= SAFE_STATE_BUDGET_US  # single-cycle arrival
    # E_STOP is terminal in software, fault or no fault
    d1 = gov.step(make_state(now_us=1_000, brake=0.0), None, 1_000)
    d2 = gov.step(make_state(now_us=2_000, brake=1.0), None, 2_000)
    assert d1.mode is GovMode.E_STOP
    assert d2.mode is GovMode.E_STOP
    assert d2.admitted is None
    assert_latency_budget(gov)


def test_braking_loss_injection(make_governor, make_state, make_cmd):
    gov = make_governor()
    decisions = run_sustained(gov, make_state, make_cmd, fault=Fault.BRAKING_LOSS, cycles=3)
    assert decisions[0].mode is GovMode.E_STOP
    assert all(d.admitted is None for d in decisions)
    assert_latency_budget(gov)


# ---------------------------------------------------------------- unmodeled


def test_unmodeled_fault_defaults_to_controlled_stop_never_nominal(
    make_governor, make_state, make_cmd
):
    gov = make_governor(network_loss_timeout_us=1_000_000)
    decisions = run_sustained(gov, make_state, make_cmd, fault=Fault.UNMODELED, cycles=6)
    assert decisions[-1].mode is GovMode.CONTROLLED_STOP  # the fail-safe default
    rungs = [list(GovMode).index(d.mode) for d in decisions]
    assert rungs == sorted(rungs, reverse=False)  # monotonic descent under sustained fault
    assert rungs[0] > list(GovMode).index(GovMode.NOMINAL)
    assert_latency_budget(gov)


def test_proximity_estop_injection(make_governor, make_state, make_cmd):
    gov = make_governor()
    d0 = gov.step(
        make_state(now_us=0, obstacle=10.0), make_cmd(issued_us=0), 0, fault=Fault.PROXIMITY_E_STOP
    )
    assert d0.mode is GovMode.E_STOP
    assert d0.admitted is None
    assert_latency_budget(gov)


# -------------------------------------------------------------------- matrix


@pytest.mark.parametrize(
    ("fault", "state_kwargs", "expected"),
    [
        (Fault.SPOOFED_COMMAND, {}, GovMode.CONTROLLED_STOP),
        (Fault.STALE_HEARTBEAT, {}, GovMode.HOLD),
        (Fault.SENSOR_LOSS, {"v": float("nan")}, GovMode.HOLD),
        (Fault.NETWORK_LOSS, {}, GovMode.CONTROLLED_STOP),
        (Fault.WATCHDOG_MISS, {}, GovMode.CONTROLLED_STOP),
        (Fault.BRAKING_LOSS, {}, GovMode.E_STOP),
        (Fault.PROXIMITY_E_STOP, {}, GovMode.E_STOP),
        (Fault.UNMODELED, {}, GovMode.CONTROLLED_STOP),
    ],
)
def test_every_fault_class_reaches_its_defined_safe_state_within_budget(
    make_governor, make_state, make_cmd, fault, state_kwargs, expected
):
    gov = make_governor(
        network_loss_timeout_us=1_000_000,
        hold_timeout_us=10_000_000,
        conservative_recovery_cycles=10_000,
    )
    drive_to_safe_state(
        gov, make_state, make_cmd,
        fault=fault, expected=expected, state_kwargs=state_kwargs,
    )
