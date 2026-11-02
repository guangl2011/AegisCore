"""CBF/RG safety filter: envelope checks, minimum-norm projection, mode gates."""

from __future__ import annotations

import math

import pytest

from aegiscore.core.model import ChassisProfile, GovernorDecision, Kinematics
from aegiscore.governor import Fault, GovernorCore, GovMode

# sqrt(2 * brake_decel(1.5) * (d=0.8 - margin=0.5)) — the proximity barrier.
V_BARRIER_D080 = math.sqrt(2.0 * 1.5 * 0.3)


def test_unfiltered_command_stays_nominal(make_governor, make_state, make_cmd):
    gov = make_governor()
    decision = gov.step(
        make_state(now_us=0, obstacle=None), make_cmd(target_speed=0.5, issued_us=0), 0
    )
    assert decision.mode is GovMode.NOMINAL
    assert decision.admitted is not None
    assert decision.admitted.command_type == "drive_speed"
    assert decision.admitted.value == 0.5
    assert decision.reason is None
    assert decision.margins["speed_mps"] == pytest.approx(0.5)


def test_min_norm_projection_onto_proximity_barrier(make_governor, make_state, make_cmd):
    """A request beyond the barrier is corrected by the smallest admissible amount."""
    gov = make_governor()
    decision = gov.step(
        make_state(now_us=0, obstacle=0.8), make_cmd(target_speed=0.96, issued_us=0), 0
    )
    assert decision.mode is GovMode.FILTERED
    assert decision.reason == "min_norm_projection"
    assert decision.admitted is not None
    assert decision.admitted.value == pytest.approx(V_BARRIER_D080)
    # the projection is the min-norm correction: never larger than requested
    assert abs(decision.admitted.value) <= abs(0.96)


def test_proximity_inside_e_stop_radius_is_immediate_e_stop(make_governor, make_state, make_cmd):
    gov = make_governor()
    decision = gov.step(make_state(now_us=0, obstacle=0.1), make_cmd(issued_us=0), 0)
    assert decision.mode is GovMode.E_STOP
    assert decision.reason == "proximal_e_stop"
    assert decision.admitted is None  # torque removal, not a drive command


def test_infeasible_barrier_brakes_and_descends_to_conservative(
    make_governor, make_state, make_cmd
):
    """Obstacle inside the safe margin: no admissible speed — brake and descend."""
    gov = make_governor()
    d0 = gov.step(make_state(now_us=0, obstacle=0.4), make_cmd(issued_us=0), 0)
    assert d0.admitted is not None
    assert d0.admitted.value == 0.0  # braking command
    assert d0.reason == "infeasible_safe_margin"
    assert d0.mode is GovMode.FILTERED  # walk: one rung per cycle
    d1 = gov.step(make_state(now_us=1_000, obstacle=0.4), make_cmd(issued_us=1_000), 1_000)
    assert d1.mode is GovMode.CONSERVATIVE


def test_kinetic_energy_envelope_caps_speed(make_governor, make_state, make_cmd):
    gov = make_governor(max_kinetic_energy_j=3.0)  # 60 kg -> v_ke = sqrt(2*3/60)
    v_ke = math.sqrt(2.0 * 3.0 / 60.0)
    decision = gov.step(
        make_state(now_us=0, obstacle=None), make_cmd(target_speed=0.9, issued_us=0), 0
    )
    assert decision.mode is GovMode.FILTERED
    assert decision.admitted is not None
    assert decision.admitted.value == pytest.approx(v_ke)
    assert decision.margins["kinetic_energy_j"] == pytest.approx(3.0)  # robot at rest


def test_stale_command_rejected_without_ladder_movement(make_governor, make_state, make_cmd):
    gov = make_governor()  # max_command_age_us defaults to 50_000
    cmd = make_cmd(target_speed=0.5, issued_us=-60_000)
    decision = gov.step(make_state(now_us=0), cmd, 0)
    assert decision.admitted is None
    assert decision.reason == "stale_command_rejected"
    assert decision.mode is GovMode.NOMINAL
    assert gov.safety_log.transitions() == ()  # no ladder movement
    assert decision.margins["command_age_us"] == pytest.approx(-10_000)


def test_malformed_command_rejected(make_governor, make_state, make_cmd):
    gov = make_governor()
    decision = gov.step(make_state(now_us=0), make_cmd(target_speed=None, issued_us=0), 0)
    assert decision.admitted is None
    assert decision.reason == "malformed_command_rejected"
    assert decision.mode is GovMode.NOMINAL


def test_nan_parameter_is_spoof(make_governor, make_state, make_cmd):
    gov = make_governor(network_loss_timeout_us=1_000_000)
    for i in range(4):
        now = i * 1_000
        decision = gov.step(
            make_state(now_us=now),
            make_cmd(target_speed=float("nan"), issued_us=now),
            now,
        )
    assert decision.mode is GovMode.CONTROLLED_STOP
    assert gov.safety_log.records[0].reason == "spoof_suspected"


def test_unknown_primitive_is_spoof(make_governor, make_state, make_cmd):
    gov = make_governor(network_loss_timeout_us=1_000_000)
    decision = gov.step(make_state(now_us=0), make_cmd(primitive="Teleport", issued_us=0), 0)
    assert decision.reason == "spoof_suspected"
    assert decision.mode is GovMode.FILTERED  # walk begins: one rung this cycle


def test_reverse_speed_capped(make_governor, make_state, make_cmd):
    gov = make_governor()
    decision = gov.step(make_state(now_us=0), make_cmd(target_speed=-0.9, issued_us=0), 0)
    assert decision.admitted is not None
    assert decision.admitted.value == pytest.approx(-0.3)  # reverse_speed_fraction * max
    assert decision.reason == "min_norm_projection"


def test_conservative_speed_cap_and_blade_refusal(make_governor, make_state, make_cmd):
    gov = make_governor(sensor_loss_persistent_cycles=3, conservative_recovery_cycles=10)
    gov.step(make_state(now_us=0, v=float("nan")), None, 0)  # walk step 1
    gov.step(make_state(now_us=1_000, v=float("nan")), None, 1_000)  # -> CONSERVATIVE
    motion = gov.step(make_state(now_us=2_000), make_cmd(target_speed=0.9, issued_us=2_000), 2_000)
    assert motion.mode is GovMode.CONSERVATIVE
    assert motion.admitted is not None
    assert motion.admitted.value == pytest.approx(0.3)  # conservative_speed_fraction * max
    blade = gov.step(
        make_state(now_us=3_000),
        make_cmd(primitive="SetBlade", target_speed=None, on=1.0, issued_us=3_000),
        3_000,
    )
    assert blade.admitted is None
    assert blade.reason == "high_energy_command_refused"
    assert blade.mode is GovMode.CONSERVATIVE
    blade_off = gov.step(
        make_state(now_us=4_000),
        make_cmd(primitive="SetBlade", target_speed=None, on=0.0, issued_us=4_000),
        4_000,
    )
    assert blade_off.admitted is not None
    assert blade_off.admitted.command_type == "blade_off"


def test_blade_off_takes_the_command_slot_during_faults(make_governor, make_state, make_cmd):
    """One command per cycle: blade-off outranks the braking command while the
    blade spins, then the drive takes over."""
    gov = make_governor(network_loss_timeout_us=1_000_000)
    now = 0
    d1 = gov.step(
        make_state(now_us=now),
        make_cmd(primitive="SetBlade", target_speed=None, on=1.0, issued_us=now),
        now,
    )
    assert d1.admitted is not None
    assert d1.admitted.command_type == "blade_on"
    d2 = gov.step(make_state(now_us=1_000), None, 1_000, fault=Fault.SPOOFED_COMMAND)
    assert d2.admitted is not None
    assert d2.admitted.command_type == "blade_off"
    d3 = gov.step(make_state(now_us=2_000), None, 2_000, fault=Fault.SPOOFED_COMMAND)
    assert d3.admitted is not None
    assert d3.admitted.command_type == "drive_speed"
    assert d3.admitted.value == 0.0


def test_idle_cycle_admits_nothing(make_governor, make_state, make_cmd):
    gov = make_governor()
    decision = gov.step(make_state(now_us=0), None, 0)
    assert decision.admitted is None
    assert decision.reason == "no_task_command"
    assert decision.mode is GovMode.NOMINAL


def test_filtered_recovers_to_nominal_when_margins_recover(make_governor, make_state, make_cmd):
    gov = make_governor()
    blocked = gov.step(
        make_state(now_us=0, obstacle=0.8), make_cmd(target_speed=0.96, issued_us=0), 0
    )
    assert blocked.mode is GovMode.FILTERED
    clear = gov.step(
        make_state(now_us=1_000, obstacle=10.0), make_cmd(target_speed=0.96, issued_us=1_000), 1_000
    )
    assert clear.mode is GovMode.NOMINAL  # table exit: margins recover -> NOMINAL
    assert clear.admitted is not None
    assert clear.admitted.value == pytest.approx(0.96)  # unfiltered again


def test_profile_without_drive_role_fails_fast():
    bad = ChassisProfile(
        model="no-drive",
        kinematics=Kinematics.DIFFERENTIAL,
        max_linear_speed=1.0,
        max_accel=1.0,
        max_wheel_speed=10.0,
        blade_inertia_kg_m2=None,
        actuators={"blade": "act.blade"},
    )
    with pytest.raises(ValueError, match="drive"):
        GovernorCore(bad)


def test_decision_type_is_shared_model(make_governor, make_state, make_cmd):
    decision = make_governor().step(make_state(now_us=0), make_cmd(issued_us=0), 0)
    assert isinstance(decision, GovernorDecision)
