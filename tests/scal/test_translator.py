"""Translator tests: primitive decompositions, per-kinematics behavior, errors."""

import math

import pytest

from aegiscore.core.model import TaskCommand
from aegiscore.scal.errors import InfeasibleCommandError, MalformedCommandError
from aegiscore.scal.kinematics import TwistSolution, forward_twist
from aegiscore.scal.profiles import ROLE_BLADE, ROLE_LEFT_WHEEL, ROLE_RIGHT_WHEEL, ScalProfile
from aegiscore.scal.translator import (
    BLADE_OFF,
    BLADE_ON,
    DOCK_SPEED_FRACTION,
    NOMINAL_DRIVE_MPS,
    NOMINAL_ROTATE_RAD_S,
    PRIMITIVE_DOCK,
    PRIMITIVE_FOLLOW_PATH,
    PRIMITIVE_MOVE_TO,
    PRIMITIVE_SET_BLADE,
    WHEEL_SPEED,
    ChassisCommand,
    Pose2D,
    SCALTranslator,
)

ORIGIN = Pose2D(0.0, 0.0, 0.0)


def move_to(x: float, y: float, theta: float) -> TaskCommand:
    return TaskCommand(
        primitive=PRIMITIVE_MOVE_TO, params={"x": x, "y": y, "theta": theta}, issued_us=0
    )


def wheel_value(element: ChassisCommand, role: str) -> float:
    target = element.targets[role]
    assert target.command_type == WHEEL_SPEED
    return target.value


def test_moveto_differential_full_decomposition(diff_profile: ScalProfile) -> None:
    # Target at bearing 45 deg, distance 1 m, final heading -45 deg.
    target = move_to(math.cos(math.pi / 4), math.sin(math.pi / 4), -math.pi / 4)
    elements = SCALTranslator().translate(target, diff_profile, ORIGIN)

    assert [e.source for e in elements] == ["MoveTo:rotate_in", "MoveTo:drive", "MoveTo:rotate_out"]
    rotate_in, drive, rotate_out = elements
    # Durations in microseconds: phi/omega and dist/v, rounded to integer us.
    assert rotate_in.duration_us == pytest.approx(
        (math.pi / 4) / NOMINAL_ROTATE_RAD_S * 1e6, rel=1e-6
    )
    assert rotate_out.duration_us == pytest.approx(
        (math.pi / 2) / NOMINAL_ROTATE_RAD_S * 1e6, rel=1e-6
    )
    assert drive.duration_us == pytest.approx(1.0 / NOMINAL_DRIVE_MPS * 1e6, rel=1e-6)
    # Every element inherits the command's issued_us for freshness checks.
    assert all(e.issued_us == target.issued_us for e in elements)
    # Drive targets: equal wheels at nominal speed (capped to the profile box).
    v = min(NOMINAL_DRIVE_MPS, diff_profile.core.max_linear_speed)
    wheel = v / diff_profile.geometry.wheel_radius_m
    assert wheel_value(drive, ROLE_LEFT_WHEEL) == pytest.approx(wheel, rel=1e-9)
    assert wheel_value(drive, ROLE_RIGHT_WHEEL) == pytest.approx(wheel, rel=1e-9)


def test_moveto_differential_straight_ahead_is_single_drive(diff_profile: ScalProfile) -> None:
    elements = SCALTranslator().translate(move_to(2.0, 0.0, 0.0), diff_profile, ORIGIN)
    assert [e.source for e in elements] == ["MoveTo:drive"]


def test_moveto_differential_same_pose_is_empty(diff_profile: ScalProfile) -> None:
    assert SCALTranslator().translate(move_to(0.0, 0.0, 0.0), diff_profile, ORIGIN) == []


def test_moveto_differential_pure_rotation(diff_profile: ScalProfile) -> None:
    elements = SCALTranslator().translate(move_to(0.0, 0.0, math.pi), diff_profile, ORIGIN)
    assert [e.source for e in elements] == ["MoveTo:rotate_out"]
    assert elements[0].duration_us == pytest.approx(
        math.pi / NOMINAL_ROTATE_RAD_S * 1e6, rel=1e-6
    )


def test_moveto_differential_respects_context_pose(diff_profile: ScalProfile) -> None:
    # Robot already at 90 deg heading; target dead ahead, same heading.
    elements = SCALTranslator().translate(
        move_to(0.0, 1.0, math.pi / 2), diff_profile, Pose2D(0.0, 0.0, math.pi / 2)
    )
    assert [e.source for e in elements] == ["MoveTo:drive"]


def _arc_twist(profile: ScalProfile, element: ChassisCommand) -> tuple[float, float]:
    """Recover the body twist of an arc element from its rear-wheel targets."""
    left = element.targets["rear_left_wheel"].value
    right = element.targets["rear_right_wheel"].value
    radius = profile.geometry.wheel_radius_m
    v = radius * (right + left) / 2.0
    omega = radius * (right - left) / profile.geometry.track_width_m
    return v, omega


def _integrate_arc(
    profile: ScalProfile, element: ChassisCommand, steps: int = 10_000
) -> tuple[float, float, float]:
    """Numerically integrate a single-arc Ackermann element to its end pose.

    Euler integration at 10k steps accumulates ~2e-5 m of drift over these
    arcs; assertions against the landing pose use a 1e-4 m tolerance.
    """
    v, omega = _arc_twist(profile, element)
    duration_s = element.duration_us / 1e6
    x = y = theta = 0.0
    dt = duration_s / steps
    for _ in range(steps):
        x += v * math.cos(theta) * dt
        y += v * math.sin(theta) * dt
        theta += omega * dt
    return x, y, theta


def test_moveto_ackermann_single_arc_lands_on_target(ackermann_profile: ScalProfile) -> None:
    x, y = 3.0, 1.0
    elements = SCALTranslator().translate(move_to(x, y, 0.0), ackermann_profile, ORIGIN)
    assert len(elements) == 1
    assert elements[0].source == "MoveTo:arc"
    end_x, end_y, _ = _integrate_arc(ackermann_profile, elements[0])
    assert end_x == pytest.approx(x, abs=1e-4)
    assert end_y == pytest.approx(y, abs=1e-4)


def test_moveto_ackermann_arc_heading_change_is_twice_bearing(
    ackermann_profile: ScalProfile,
) -> None:
    # Documented behavior: the arc always turns exactly 2*bearing; missions
    # needing a specific approach heading use FollowPath's straight segments.
    x, y = 3.0, 1.0
    bearing = math.atan2(y, x)
    elements = SCALTranslator().translate(move_to(x, y, 0.0), ackermann_profile, ORIGIN)
    _x, _y, end_theta = _integrate_arc(ackermann_profile, elements[0])
    assert end_theta == pytest.approx(2.0 * bearing, abs=1e-6)


def test_moveto_ackermann_straight_is_single_drive(ackermann_profile: ScalProfile) -> None:
    elements = SCALTranslator().translate(move_to(4.0, 0.0, 0.0), ackermann_profile, ORIGIN)
    assert [e.source for e in elements] == ["MoveTo:drive"]
    assert elements[0].targets["steer_left"].value == 0.0
    assert elements[0].targets["steer_right"].value == 0.0


def test_moveto_ackermann_behind_is_infeasible(ackermann_profile: ScalProfile) -> None:
    with pytest.raises(InfeasibleCommandError, match="behind or abeam the axle"):
        SCALTranslator().translate(move_to(-1.0, 0.0, 0.0), ackermann_profile, ORIGIN)


def test_moveto_ackermann_too_tight_is_infeasible(ackermann_profile: ScalProfile) -> None:
    # Required curvature 2*sin(bearing)/dist far exceeds the steering bound.
    with pytest.raises(InfeasibleCommandError, match="beyond the chassis bound"):
        SCALTranslator().translate(move_to(0.3, 0.5, 0.0), ackermann_profile, ORIGIN)


def test_moveto_ackermann_same_position_differs_only_in_heading_is_infeasible(
    ackermann_profile: ScalProfile,
) -> None:
    with pytest.raises(InfeasibleCommandError, match="in-place rotation"):
        SCALTranslator().translate(move_to(0.0, 0.0, 1.0), ackermann_profile, ORIGIN)


def test_moveto_ackermann_arc_twist_roundtrips_through_forward(
    ackermann_profile: ScalProfile,
) -> None:
    elements = SCALTranslator().translate(move_to(3.0, 1.0, 0.0), ackermann_profile, ORIGIN)
    _v, omega = _arc_twist(ackermann_profile, elements[0])
    # The arc twist is v * kappa with kappa = 2*dy/dist^2.
    dist = math.hypot(3.0, 1.0)
    bearing = math.atan2(1.0, 3.0)
    kappa = 2.0 * math.sin(bearing) / dist  # == 2*dy/dist^2
    v = _arc_twist(ackermann_profile, elements[0])[0]
    assert omega == pytest.approx(v * kappa, rel=1e-9)


def test_follow_path_differential_decomposition(diff_profile: ScalProfile) -> None:
    length, curvature, speed = 2.0, 0.5, 0.6
    cmd = TaskCommand(
        primitive=PRIMITIVE_FOLLOW_PATH,
        params={"n_segments": 1.0, "seg0_len": length, "seg0_curv": curvature, "seg0_speed": speed},
        issued_us=0,
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    assert [e.source for e in elements] == ["FollowPath:seg0"]
    element = elements[0]
    assert element.duration_us == pytest.approx(length / speed * 1e6, rel=1e-6)
    omega = speed * curvature
    wheel_r = diff_profile.geometry.wheel_radius_m
    half_track = diff_profile.geometry.track_width_m / 2.0
    assert wheel_value(element, ROLE_LEFT_WHEEL) == pytest.approx(
        (speed - omega * half_track) / wheel_r, rel=1e-9
    )
    assert wheel_value(element, ROLE_RIGHT_WHEEL) == pytest.approx(
        (speed + omega * half_track) / wheel_r, rel=1e-9
    )


def test_follow_path_multi_segment(diff_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_FOLLOW_PATH,
        params={
            "n_segments": 3.0,
            "seg0_len": 1.0, "seg0_curv": 0.0, "seg0_speed": 0.5,
            "seg1_len": 2.0, "seg1_curv": -0.4, "seg1_speed": 0.5,
            "seg2_len": 0.5, "seg2_curv": 0.2, "seg2_speed": 0.5,
        },
        issued_us=0,
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    assert [e.source for e in elements] == [
        "FollowPath:seg0",
        "FollowPath:seg1",
        "FollowPath:seg2",
    ]


def test_follow_path_speed_over_limit_is_capped(diff_profile: ScalProfile) -> None:
    wheel_r = diff_profile.geometry.wheel_radius_m
    over_limit_speed = diff_profile.core.max_linear_speed * 10.0
    cmd = TaskCommand(
        primitive=PRIMITIVE_FOLLOW_PATH,
        params={
            "n_segments": 1.0,
            "seg0_len": 1.0,
            "seg0_curv": 0.0,
            "seg0_speed": over_limit_speed,
        },
        issued_us=0,
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    wheel_speed = wheel_value(elements[0], ROLE_LEFT_WHEEL)
    assert wheel_speed <= diff_profile.core.max_wheel_speed
    # Duration is recomputed for the capped speed, so the segment still completes.
    assert elements[0].duration_us == pytest.approx(1.0 / (wheel_speed * wheel_r) * 1e6, rel=1e-6)


def test_follow_path_ackermann_over_curvature_is_infeasible(ackermann_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_FOLLOW_PATH,
        params={"n_segments": 1.0, "seg0_len": 1.0, "seg0_curv": 5.0, "seg0_speed": 1.0},
        issued_us=0,
    )
    with pytest.raises(InfeasibleCommandError, match="exceeds the chassis bound"):
        SCALTranslator().translate(cmd, ackermann_profile, ORIGIN)


@pytest.mark.parametrize("bad", [0.0, -1.0, 2.5])
def test_follow_path_rejects_bad_segment_count(diff_profile: ScalProfile, bad: float) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_FOLLOW_PATH,
        params={"n_segments": bad, "seg0_len": 1.0, "seg0_curv": 0.0, "seg0_speed": 0.5},
        issued_us=0,
    )
    with pytest.raises(MalformedCommandError, match="n_segments"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


@pytest.mark.parametrize("primitive", [PRIMITIVE_MOVE_TO, PRIMITIVE_FOLLOW_PATH, PRIMITIVE_DOCK])
def test_missing_params_are_malformed(diff_profile: ScalProfile, primitive: str) -> None:
    cmd = TaskCommand(primitive=primitive, params={}, issued_us=0)
    with pytest.raises(MalformedCommandError, match="missing required param"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


def test_unknown_primitive_is_malformed(diff_profile: ScalProfile) -> None:
    cmd = TaskCommand(primitive="Teleport", params={"x": 1.0}, issued_us=0)
    with pytest.raises(MalformedCommandError, match="unknown primitive"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


# --- SetBlade -----------------------------------------------------------------


def test_set_blade_on(diff_profile: ScalProfile) -> None:
    blade_max = diff_profile.geometry.blade_max_speed_rad_s
    assert blade_max is not None
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE,
        params={"enabled": 1.0, "speed": 0.7 * blade_max},
        issued_us=0,
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    assert len(elements) == 1
    assert elements[0].source == "SetBlade"
    blade_target = elements[0].targets[ROLE_BLADE]
    assert blade_target.command_type == BLADE_ON
    assert blade_target.value == pytest.approx(0.7 * blade_max)


def test_set_blade_enabled_at_zero_speed_stays_on(diff_profile: ScalProfile) -> None:
    # enabled=1 keys the command type; speed 0 means "on, at zero rad/s".
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE, params={"enabled": 1.0, "speed": 0.0}, issued_us=0
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    blade_target = elements[0].targets[ROLE_BLADE]
    assert blade_target.command_type == BLADE_ON
    assert blade_target.value == 0.0


def test_set_blade_disabled_is_off(diff_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE, params={"enabled": 0.0, "speed": 0.0}, issued_us=0
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    blade_target = elements[0].targets[ROLE_BLADE]
    assert blade_target.command_type == BLADE_OFF
    assert blade_target.value == 0.0


def test_set_blade_over_limit_is_infeasible(diff_profile: ScalProfile) -> None:
    blade_max = diff_profile.geometry.blade_max_speed_rad_s
    assert blade_max is not None
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE,
        params={"enabled": 1.0, "speed": blade_max * 1.01},
        issued_us=0,
    )
    with pytest.raises(InfeasibleCommandError, match="exceeds the actuator"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


def test_set_blade_negative_speed_is_malformed(diff_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE, params={"enabled": 1.0, "speed": -0.1}, issued_us=0
    )
    with pytest.raises(MalformedCommandError, match="non-negative"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


def test_set_blade_enabled_needs_speed(diff_profile: ScalProfile) -> None:
    cmd = TaskCommand(primitive=PRIMITIVE_SET_BLADE, params={"enabled": 1.0}, issued_us=0)
    with pytest.raises(MalformedCommandError, match="missing required param 'speed'"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


@pytest.mark.parametrize("bad", [-0.5, 0.5, 2.0])
def test_set_blade_rejects_non_boolean_enabled(diff_profile: ScalProfile, bad: float) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE, params={"enabled": bad, "speed": 0.0}, issued_us=0
    )
    with pytest.raises(MalformedCommandError, match="must be 0.0 or 1.0"):
        SCALTranslator().translate(cmd, diff_profile, ORIGIN)


def test_set_blade_on_bladeless_chassis_is_infeasible(ackermann_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_SET_BLADE, params={"enabled": 1.0, "speed": 0.0}, issued_us=0
    )
    with pytest.raises(InfeasibleCommandError, match="no blade actuator"):
        SCALTranslator().translate(cmd, ackermann_profile, ORIGIN)


# --- Dock ---------------------------------------------------------------------


def test_dock_differential_runs_at_quarter_speed_and_stops_blade(
    diff_profile: ScalProfile,
) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_DOCK, params={"x": 1.0, "y": 0.0, "theta": 0.0}, issued_us=0
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    # Already facing the dock: no rotation needed.
    assert [e.source for e in elements] == ["Dock:drive", "Dock:blade_off"]
    drive = elements[0]
    expected_wheel = NOMINAL_DRIVE_MPS * DOCK_SPEED_FRACTION / diff_profile.geometry.wheel_radius_m
    assert wheel_value(drive, ROLE_LEFT_WHEEL) == pytest.approx(expected_wheel)
    assert wheel_value(drive, ROLE_RIGHT_WHEEL) == pytest.approx(expected_wheel)
    # Blade-off is always the final dock element.
    assert elements[-1].targets[ROLE_BLADE].command_type == BLADE_OFF
    assert elements[-1].targets[ROLE_BLADE].value == 0.0


def test_dock_diff_with_approach_rotation(diff_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_DOCK, params={"x": 0.0, "y": 1.0, "theta": math.pi / 2}, issued_us=0
    )
    elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
    # Final heading equals the approach bearing, so no rotate_out is needed.
    assert [e.source for e in elements] == ["Dock:rotate_in", "Dock:drive", "Dock:blade_off"]
    assert elements[1].duration_us == pytest.approx(
        1.0 / (NOMINAL_DRIVE_MPS * DOCK_SPEED_FRACTION) * 1e6, rel=1e-6
    )


def test_dock_ackermann_arc_and_blade_off(ackermann_profile: ScalProfile) -> None:
    cmd = TaskCommand(
        primitive=PRIMITIVE_DOCK, params={"x": 5.0, "y": 1.0, "theta": 0.0}, issued_us=0
    )
    elements = SCALTranslator().translate(cmd, ackermann_profile, ORIGIN)
    # The reference UTV has no blade, so the stream is the approach arc only.
    assert [e.source for e in elements] == ["Dock:arc"]
    end_x, end_y, _ = _integrate_arc(ackermann_profile, elements[0])
    assert end_x == pytest.approx(5.0, abs=1e-4)
    assert end_y == pytest.approx(1.0, abs=1e-4)


def test_dock_actuator_values_are_within_limits_everywhere(diff_profile: ScalProfile) -> None:
    for target_x in (-2.0, -0.5, 0.5, 2.0):
        cmd = TaskCommand(
            primitive=PRIMITIVE_DOCK, params={"x": target_x, "y": 0.5, "theta": 0.0}, issued_us=0
        )
        elements = SCALTranslator().translate(cmd, diff_profile, ORIGIN)
        for element in elements:
            for target in element.targets.values():
                assert abs(target.value) <= diff_profile.core.max_wheel_speed


# --- Twist translation and determinism -----------------------------------------


def test_translate_twist_matches_solver(diff_profile: ScalProfile) -> None:
    element = SCALTranslator().translate_twist(
        diff_profile, 0.4, 1.0, issued_us=42, duration_us=50_000
    )
    wheel_r = diff_profile.geometry.wheel_radius_m
    half_track = diff_profile.geometry.track_width_m / 2.0
    assert element.issued_us == 42
    assert element.duration_us == 50_000
    assert element.source == "Twist"
    assert wheel_value(element, ROLE_LEFT_WHEEL) == pytest.approx(
        (0.4 - 1.0 * half_track) / wheel_r
    )
    assert wheel_value(element, ROLE_RIGHT_WHEEL) == pytest.approx(
        (0.4 + 1.0 * half_track) / wheel_r
    )


def test_translate_twist_refuses_inadmissible(ackermann_profile: ScalProfile) -> None:
    with pytest.raises(InfeasibleCommandError):
        SCALTranslator().translate_twist(ackermann_profile, 0.0, 1.0)


def test_translation_is_deterministic(diff_profile: ScalProfile) -> None:
    translator = SCALTranslator()
    cmd = move_to(1.0, 0.5, 0.2)
    first = translator.translate(cmd, diff_profile, ORIGIN)
    second = translator.translate(cmd, diff_profile, ORIGIN)
    assert first == second


def test_motion_elements_decode_via_forward_kinematics(diff_profile: ScalProfile) -> None:
    """Reconstructing a TwistSolution from an element decodes to the commanded twist."""
    translator = SCALTranslator()
    elements = translator.translate(move_to(2.0, 1.0, -0.3), diff_profile, ORIGIN)
    for element in elements:
        solution = TwistSolution(
            wheel_speeds={
                role: t.value
                for role, t in element.targets.items()
                if t.command_type == WHEEL_SPEED
            },
            steering_angles={},
        )
        v, omega = forward_twist(diff_profile, solution)
        if element.source.endswith("rotate_in"):
            assert v == pytest.approx(0.0, abs=1e-12)
            assert abs(omega) == pytest.approx(NOMINAL_ROTATE_RAD_S, rel=1e-9)
        elif element.source.endswith("rotate_out"):
            assert v == pytest.approx(0.0, abs=1e-12)
            assert abs(omega) == pytest.approx(NOMINAL_ROTATE_RAD_S, rel=1e-9)
        elif element.source.endswith("drive"):
            assert omega == pytest.approx(0.0, abs=1e-12)
            assert v == pytest.approx(
                min(NOMINAL_DRIVE_MPS, diff_profile.core.max_linear_speed), rel=1e-9
            )
