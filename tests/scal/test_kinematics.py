"""Kinematic solver tests: known values, forward/inverse consistency, envelope.

The hypothesis properties construct admissible twists per family (direct
parameterization, so no rejection waste) and assert the two core guarantees:
forward/inverse roundtrip and actuator-limit containment.
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aegiscore.core.model import Kinematics
from aegiscore.scal.errors import InfeasibleCommandError
from aegiscore.scal.kinematics import (
    forward_twist,
    is_admissible,
    max_curvature_for_speed,
    solve_twist,
)
from aegiscore.scal.profiles import ROLE_LEFT_WHEEL, ROLE_RIGHT_WHEEL, ScalProfile

TOL = 1e-9


def _omega_bound(profile: ScalProfile, v: float) -> float:
    """Largest |omega| keeping the wheels inside the actuator limit at v."""
    limit = profile.core.max_wheel_speed * profile.geometry.wheel_radius_m
    return 2.0 * (limit - abs(v)) / profile.geometry.track_width_m


def _admissible_twists(profile: ScalProfile):
    """Strategy: admissible (v, omega) pairs, built to satisfy the envelope."""
    vmax = profile.core.max_linear_speed
    spin = profile.geometry.max_spin_rad_s
    if profile.kinematics is Kinematics.ACKERMANN:
        kappa_max = max_curvature_for_speed(profile, 0.9 * vmax)
        speeds = st.floats(min_value=0.05, max_value=0.9).flatmap(
            lambda frac: st.booleans().flatmap(
                lambda sign: st.just((1.0 if sign else -1.0) * frac * vmax)
            )
        )
        kappas = st.floats(min_value=-0.9, max_value=0.9).map(lambda f: f * kappa_max)
        return st.tuples(speeds, kappas).map(
            lambda pair: (pair[0], pair[0] * pair[1])  # omega = v * kappa
        )
    v = st.floats(min_value=-0.9, max_value=0.9).map(lambda frac: frac * vmax)
    assert spin is not None
    return v.flatmap(
        lambda speed: st.tuples(
            st.just(speed),
            st.floats(min_value=-0.95, max_value=0.95).map(
                lambda frac: frac * min(spin, _omega_bound(profile, speed))
            ),
        )
    )


# --- Differential (unicycle) -------------------------------------------------


def test_differential_known_values(diff_profile) -> None:
    # v=0.5, omega=1.0, track=0.44, radius=0.1:
    # left = (0.5 - 0.22)/0.1 = 2.8, right = (0.5 + 0.22)/0.1 = 7.2
    solution = solve_twist(diff_profile, 0.5, 1.0)
    assert math.isclose(solution.wheel_speeds[ROLE_LEFT_WHEEL], 2.8, abs_tol=TOL)
    assert math.isclose(solution.wheel_speeds[ROLE_RIGHT_WHEEL], 7.2, abs_tol=TOL)
    assert solution.steering_angles == {}


def test_differential_spin_in_place_is_symmetric(diff_profile) -> None:
    solution = solve_twist(diff_profile, 0.0, 2.0)
    left = solution.wheel_speeds[ROLE_LEFT_WHEEL]
    right = solution.wheel_speeds[ROLE_RIGHT_WHEEL]
    assert math.isclose(left, -right, abs_tol=TOL)
    assert left < 0 < right  # left turns clockwise wheels backwards


def test_differential_straight_is_equal_wheels(diff_profile) -> None:
    solution = solve_twist(diff_profile, 1.2, 0.0)
    assert math.isclose(
        solution.wheel_speeds[ROLE_LEFT_WHEEL],
        solution.wheel_speeds[ROLE_RIGHT_WHEEL],
        abs_tol=TOL,
    )


def test_differential_roundtrip_known_values(diff_profile) -> None:
    solution = solve_twist(diff_profile, 0.5, 1.0)
    assert forward_twist(diff_profile, solution) == pytest.approx((0.5, 1.0), abs=TOL)


# --- Ackermann (inverse bicycle) ---------------------------------------------


def test_ackermann_straight_has_zero_steer(ackermann_profile) -> None:
    solution = solve_twist(ackermann_profile, 2.0, 0.0)
    left = solution.wheel_speeds["rear_left_wheel"]
    right = solution.wheel_speeds["rear_right_wheel"]
    assert left == right
    assert solution.steering_angles == {"steer_left": 0.0, "steer_right": 0.0}


def test_ackermann_known_values(ackermann_profile) -> None:
    # v=2.0, omega=0.5 -> R_c=4.0; track=1.1 -> R_l=3.45, R_r=4.55
    solution = solve_twist(ackermann_profile, 2.0, 0.5)
    wheel_r = ackermann_profile.geometry.wheel_radius_m
    assert math.isclose(
        solution.wheel_speeds["rear_left_wheel"], 0.5 * 3.45 / wheel_r, rel_tol=1e-12
    )
    assert math.isclose(
        solution.wheel_speeds["rear_right_wheel"], 0.5 * 4.55 / wheel_r, rel_tol=1e-12
    )
    wheelbase = ackermann_profile.geometry.wheelbase_m
    assert wheelbase is not None
    assert math.isclose(
        solution.steering_angles["steer_left"], math.atan(wheelbase / 3.45), rel_tol=1e-12
    )
    assert math.isclose(
        solution.steering_angles["steer_right"], math.atan(wheelbase / 4.55), rel_tol=1e-12
    )
    # Inner wheel steers more and spins slower.
    assert abs(solution.steering_angles["steer_left"]) > abs(
        solution.steering_angles["steer_right"]
    )
    assert solution.wheel_speeds["rear_left_wheel"] < solution.wheel_speeds["rear_right_wheel"]


def test_ackermann_both_steers_agree_on_turn_center(ackermann_profile) -> None:
    """Independent verification: each steer angle must recover the same R_c."""
    solution = solve_twist(ackermann_profile, 3.0, 0.8)
    half_track = ackermann_profile.geometry.track_width_m / 2.0
    wheelbase = ackermann_profile.geometry.wheelbase_m
    assert wheelbase is not None
    radius_from_left = wheelbase / math.tan(solution.steering_angles["steer_left"]) + half_track
    radius_from_right = wheelbase / math.tan(solution.steering_angles["steer_right"]) - half_track
    assert math.isclose(radius_from_left, radius_from_right, rel_tol=1e-9)


def test_ackermann_right_turn_mirrors_left(ackermann_profile) -> None:
    left_turn = solve_twist(ackermann_profile, 2.0, 0.5)
    right_turn = solve_twist(ackermann_profile, 2.0, -0.5)
    # Mirror across the centerline: the left wheel is inner on a left turn but
    # outer on a right turn, so steer_left pairs with -steer_right.
    assert math.isclose(
        left_turn.steering_angles["steer_left"],
        -right_turn.steering_angles["steer_right"],
        abs_tol=TOL,
    )
    assert math.isclose(
        left_turn.steering_angles["steer_right"],
        -right_turn.steering_angles["steer_left"],
        abs_tol=TOL,
    )
    assert math.isclose(
        left_turn.wheel_speeds["rear_left_wheel"],
        right_turn.wheel_speeds["rear_right_wheel"],
        abs_tol=TOL,
    )


def test_ackermann_cannot_rotate_in_place(ackermann_profile) -> None:
    # Refused by the motion-envelope pre-check (the solver's specific message
    # is only reached when admissibility passes); the refusal is the contract.
    with pytest.raises(InfeasibleCommandError):
        solve_twist(ackermann_profile, 0.0, 1.0)


def test_ackermann_at_max_steer_the_inner_wheel_is_still_legal(ackermann_profile) -> None:
    kappa_max = max_curvature_for_speed(
        ackermann_profile, 0.9 * ackermann_profile.core.max_linear_speed
    )
    v = 0.9 * ackermann_profile.core.max_linear_speed
    solution = solve_twist(ackermann_profile, v, v * kappa_max)
    steer_max = ackermann_profile.geometry.max_steer_rad
    assert steer_max is not None
    assert abs(solution.steering_angles["steer_left"]) <= steer_max + TOL
    assert abs(solution.steering_angles["steer_right"]) <= steer_max + TOL


# --- Hybrid multi-motor -------------------------------------------------------


def test_hybrid_known_values(hybrid_profile) -> None:
    # v=1.0, omega=2.0, offsets +/-0.25, radius=0.125:
    # left wheels (1 - 0.5)/0.125 = 4.0, right wheels (1 + 0.5)/0.125 = 12.0
    solution = solve_twist(hybrid_profile, 1.0, 2.0)
    assert math.isclose(solution.wheel_speeds["front_left_wheel"], 4.0, abs_tol=TOL)
    assert math.isclose(solution.wheel_speeds["rear_left_wheel"], 4.0, abs_tol=TOL)
    assert math.isclose(solution.wheel_speeds["front_right_wheel"], 12.0, abs_tol=TOL)
    assert math.isclose(solution.wheel_speeds["rear_right_wheel"], 12.0, abs_tol=TOL)


def test_hybrid_spin_in_place(hybrid_profile) -> None:
    solution = solve_twist(hybrid_profile, 0.0, 2.0)
    for left_role in ("front_left_wheel", "rear_left_wheel"):
        assert solution.wheel_speeds[left_role] < 0
    for right_role in ("front_right_wheel", "rear_right_wheel"):
        assert solution.wheel_speeds[right_role] > 0


def test_hybrid_roundtrip_known_values(hybrid_profile) -> None:
    solution = solve_twist(hybrid_profile, 1.0, 2.0)
    assert forward_twist(hybrid_profile, solution) == pytest.approx((1.0, 2.0), abs=TOL)


# --- Properties: roundtrip and limit containment -----------------------------


@settings(deadline=None, max_examples=100)
@given(data=st.data())
def test_roundtrip_exact_for_all_families(
    data, diff_profile, ackermann_profile, hybrid_profile
) -> None:
    for profile in (diff_profile, ackermann_profile, hybrid_profile):
        v, omega = data.draw(_admissible_twists(profile))
        solution = solve_twist(profile, v, omega)
        recovered_v, recovered_omega = forward_twist(profile, solution)
        assert recovered_v == pytest.approx(v, abs=1e-9, rel=1e-9)
        assert recovered_omega == pytest.approx(omega, abs=1e-9, rel=1e-9)


@settings(deadline=None, max_examples=100)
@given(data=st.data())
def test_admissible_twists_never_exceed_actuator_limits(
    data, diff_profile, ackermann_profile, hybrid_profile
) -> None:
    for profile in (diff_profile, ackermann_profile, hybrid_profile):
        v, omega = data.draw(_admissible_twists(profile))
        solution = solve_twist(profile, v, omega)
        for role, speed in solution.wheel_speeds.items():
            assert abs(speed) <= profile.core.max_wheel_speed + TOL, (
                f"{profile.model}: {role} at {speed} rad/s exceeds "
                f"{profile.core.max_wheel_speed} (v={v}, omega={omega})"
            )
        steer_max = profile.geometry.max_steer_rad
        for _role, angle in solution.steering_angles.items():
            assert steer_max is not None and abs(angle) <= steer_max + TOL


@settings(deadline=None, max_examples=50)
@given(data=st.data())
def test_inadmissible_twists_are_refused(
    data, diff_profile, ackermann_profile, hybrid_profile
) -> None:
    # Above top speed: refused on every family.
    with pytest.raises(InfeasibleCommandError):
        solve_twist(diff_profile, 1.001 * diff_profile.core.max_linear_speed, 0.0)
    with pytest.raises(InfeasibleCommandError):
        solve_twist(hybrid_profile, 1.001 * hybrid_profile.core.max_linear_speed, 0.0)
    with pytest.raises(InfeasibleCommandError):
        solve_twist(ackermann_profile, 1.001 * ackermann_profile.core.max_linear_speed, 0.0)
    # Beyond the spin bound: refused on the rotate-in-place families.
    spin = diff_profile.geometry.max_spin_rad_s
    assert spin is not None
    with pytest.raises(InfeasibleCommandError):
        solve_twist(diff_profile, 0.0, 1.01 * spin)
    # Ackermann never rotates in place.
    with pytest.raises(InfeasibleCommandError):
        solve_twist(ackermann_profile, 0.0, 0.1)


def test_solver_functions_agree_with_envelope_predicate(diff_profile) -> None:
    # Boundary consistency: the envelope predicate and solve_twist agree.
    spin = diff_profile.geometry.max_spin_rad_s
    assert spin is not None
    assert is_admissible(diff_profile, 0.0, spin)
    assert not is_admissible(diff_profile, 0.0, spin * 1.01)
