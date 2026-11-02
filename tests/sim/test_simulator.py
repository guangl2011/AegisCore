"""Unit tests for the deterministic chassis simulator."""

from __future__ import annotations

import math

import pytest

from aegiscore.scal.profiles import REFERENCE_PROFILES
from aegiscore.sim import SIM_DT_US, ChassisSim, KinematicViolation

ALL_PROFILES = list(REFERENCE_PROFILES.values())


def test_default_timestep_is_beneath_watchdog_and_heartbeat_thresholds() -> None:
    # 10 ms per cycle keeps nominal runs from tripping the 20 ms watchdog and
    # 100 ms heartbeat lease by construction.
    assert SIM_DT_US == 10_000


def test_invalid_timestep_rejected() -> None:
    with pytest.raises(ValueError, match="dt_us"):
        ChassisSim(ALL_PROFILES[0], dt_us=0)


def test_reset_starts_at_origin_at_rest_blade_off() -> None:
    for profile in ALL_PROFILES:
        sim = ChassisSim(profile)
        assert sim.pose == (0.0, 0.0, 0.0)
        assert sim.velocity == (0.0, 0.0)
        assert sim.steps == 0
        assert sim.violations == ()


def test_straight_integration_matches_analytic_pose() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    v = 0.8 * profile.core.max_linear_speed
    for _ in range(50):
        sim.integrate(v, 0.0)
    x, y, theta = sim.pose
    expected = 50 * v * (SIM_DT_US / 1_000_000.0)
    assert theta == pytest.approx(0.0, abs=1e-12)
    assert math.hypot(x, y) == pytest.approx(expected, rel=1e-9)
    assert sim.steps == 50


def test_in_place_rotation_advances_heading_without_translation() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    omega = 0.5  # rad/s, well inside the envelope
    for _ in range(40):
        sim.integrate(0.0, omega)
    x, y, theta = sim.pose
    assert math.hypot(x, y) == pytest.approx(0.0, abs=1e-12)
    assert theta == pytest.approx(omega * 40 * (SIM_DT_US / 1_000_000.0), rel=1e-9)


def test_deterministic_across_instances() -> None:
    profile = REFERENCE_PROFILES["ref-hybrid-mower"]

    def run() -> list[tuple[float, float, float]]:
        sim = ChassisSim(profile)
        twist_sequence = [(0.9, 0.0), (0.7, 0.3), (0.0, 0.6), (0.5, -0.2)] * 25
        for v, omega in twist_sequence:
            sim.integrate(v, omega)
        return [sim.pose, sim.velocity]

    assert run() == run()


def test_over_speed_execution_is_counted_as_violation() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    sim.integrate(profile.core.max_linear_speed + 0.01, 0.0)
    assert len(sim.violations) == 1
    violation = sim.violations[0]
    assert violation.step_index == 0
    assert violation.v_mps == pytest.approx(profile.core.max_linear_speed + 0.01)
    assert profile.model in violation.detail


def test_over_speed_on_any_chassis_is_counted() -> None:
    for profile in ALL_PROFILES:
        sim = ChassisSim(profile)
        sim.integrate(profile.core.max_linear_speed * 2.0, 0.0)
        assert len(sim.violations) == 1, profile.model


def test_out_of_envelope_yaw_rate_is_counted() -> None:
    profile = REFERENCE_PROFILES["ref-ack-utv"]
    sim = ChassisSim(profile)
    # Ackermann chassis cannot spin in place at all.
    sim.integrate(0.0, 0.5)
    assert len(sim.violations) == 1
    assert sim.violations[0].omega_rad_s == pytest.approx(0.5)


def test_boundary_twist_at_exact_limits_is_not_a_violation() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    sim.integrate(profile.core.max_linear_speed, 0.0)
    sim.integrate(0.0, profile.core.max_wheel_speed * profile.geometry.wheel_radius_m)
    assert sim.violations == ()


def test_violation_still_integrates_the_executed_twist() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    sim.integrate(profile.core.max_linear_speed + 0.5, 0.0)
    x, _, _ = sim.pose
    assert x > 0.0
    assert sim.velocity[0] == pytest.approx(profile.core.max_linear_speed + 0.5)


def test_governor_profile_adapter_mirrors_scal_profile() -> None:
    for profile in ALL_PROFILES:
        sim = ChassisSim(profile)
        gp = sim.governor_profile
        assert gp.model == profile.core.model
        assert gp.kinematics == profile.core.kinematics
        assert gp.max_linear_speed == profile.core.max_linear_speed
        assert gp.max_accel == profile.core.max_accel
        assert gp.max_wheel_speed == profile.core.max_wheel_speed
        # The governor must find a drive actuator to write.
        assert "drive" in gp.actuators
        assert gp.actuators["drive"] in profile.core.actuators.values()


def test_governor_profile_adapter_carries_blade_when_fitted() -> None:
    mower = REFERENCE_PROFILES["ref-diff-mower"]
    assert "blade" in ChassisSim(mower).governor_profile.actuators
    utv = REFERENCE_PROFILES["ref-ack-utv"]
    assert "blade" not in ChassisSim(utv).governor_profile.actuators


def test_make_state_reports_fresh_heartbeat_and_engaged_brake() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    sim.integrate(0.4, 0.0)
    state = sim.make_state(now_us=70_000)
    assert state.timestamp_us == 70_000
    assert state.last_heartbeat_us == 70_000  # fresh: the host is alive
    gp = sim.governor_profile
    assert state.actuator_states[gp.actuators["drive"]] == pytest.approx(0.4)
    assert state.actuator_states[gp.actuators["brake"]] == pytest.approx(1.0)
    assert state.linear_velocity == pytest.approx(0.4)
    assert state.nearest_obstacle_m is None


def test_make_state_reports_blade_speed_for_mowers() -> None:
    mower = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(mower)
    sim.set_blade(80.0)
    state = sim.make_state(0)
    blade_id = sim.governor_profile.actuators["blade"]
    assert state.actuator_states[blade_id] == pytest.approx(80.0)


def test_place_obstacle_feeds_the_proximity_reading() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    sim.place_obstacle(0.15)
    assert sim.make_state(0).nearest_obstacle_m == pytest.approx(0.15)
    sim.place_obstacle(None)
    assert sim.make_state(0).nearest_obstacle_m is None


def test_violation_records_carry_step_indices() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    sim = ChassisSim(profile)
    sim.integrate(0.1, 0.0)
    sim.integrate(99.0, 0.0)
    sim.integrate(0.1, 0.0)
    sim.integrate(99.0, 0.0)
    assert [v.step_index for v in sim.violations] == [1, 3]
    assert all(isinstance(v, KinematicViolation) for v in sim.violations)
