"""SCAL translator: task primitives -> chassis-specific command streams.

Contract (MVP):

- Input: one platform-agnostic ``TaskCommand`` plus a ``ScalProfile`` and the
  chassis context pose. Output: a deterministic list of ``ChassisCommand``
  elements. Translation is pure — same inputs, same stream, no clocks.
- ``ChassisCommand`` is SCAL's output vocabulary: desired per-actuator
  targets in chassis coordinates. It is NOT an ``ActuatorCommand`` — the
  governor is the only component allowed to emit those; it validates and
  filters this stream first.
- Primitive parameter contracts (``TaskCommand.params``, ``dict[str, float]``):

  ================= =======================================================
  MoveTo            ``x, y, theta`` — target pose in the field frame
  FollowPath        ``n_segments``, ``seg{i}_len``, ``seg{i}_curv``,
                    ``seg{i}_speed`` — tangent-continuous chain of arcs,
                    expressed in the chassis start frame
  SetBlade          ``enabled`` (1.0/0.0), ``speed`` (rad/s, required
                    when enabled)
  Dock              ``x, y, theta`` — station pose; slow approach, blade off
  ================= =======================================================

- Decompositions are kinematics-aware. Differential and hybrid chassis
  rotate in place; Ackermann chassis translate on arcs only, so a MoveTo
  target behind the axle or a pose-only rotation is infeasible, not
  approximated. An Ackermann MoveTo lands exactly on the target position;
  its final heading is the arc tangent (2 x bearing) — missions that need
  a specific approach heading use FollowPath with a straight final segment.
- Speeds are capped to the profile envelope. Adapting mission intent to
  what the chassis can physically do is SCAL's job; the governor handles
  safety filtering downstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aegiscore.core.model import Kinematics, TaskCommand
from aegiscore.scal.errors import InfeasibleCommandError, MalformedCommandError
from aegiscore.scal.kinematics import (
    TwistSolution,
    max_curvature_for_speed,
    solve_twist,
)
from aegiscore.scal.profiles import ROLE_BLADE, ScalProfile

# Command types carried by ChassisCommand targets. Superset of the core
# model's vocabulary: steering is an actuator target like wheel speed.
WHEEL_SPEED = "wheel_speed"
STEER_ANGLE = "steer_angle"
BLADE_ON = "blade_on"
BLADE_OFF = "blade_off"

# Platform-agnostic task primitives consumed by the translator.
PRIMITIVE_MOVE_TO = "MoveTo"
PRIMITIVE_FOLLOW_PATH = "FollowPath"
PRIMITIVE_SET_BLADE = "SetBlade"
PRIMITIVE_DOCK = "Dock"

# Canonical MVP mission speeds (m/s, rad/s) and fractions. Decompositions
# request these; everything is capped to the profile envelope afterwards.
NOMINAL_DRIVE_MPS = 0.8
NOMINAL_ROTATE_RAD_S = 1.0
DOCK_SPEED_FRACTION = 0.25

MAX_PATH_SEGMENTS = 16

# Tolerances: angles/offsets below these are treated as zero.
_ANGLE_EPS = 1e-9
_SPEED_EPS = 1e-9


@dataclass(frozen=True)
class Pose2D:
    """Chassis context pose in the field frame (yaw in rad)."""

    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0


@dataclass(frozen=True)
class ActuatorTarget:
    """Desired state for one logical actuator role."""

    command_type: str
    value: float


@dataclass(frozen=True)
class ChassisCommand:
    """One element of a chassis-specific command stream emitted by SCAL.

    Holds the actuator targets for one control step (``duration_us`` long)
    plus provenance. NOT an ``ActuatorCommand`` — the governor is the only
    emitter of those and validates this stream first.
    """

    targets: dict[str, ActuatorTarget]  # logical role -> target
    duration_us: int
    source: str  # e.g. "MoveTo:drive" — which decomposition step produced it
    issued_us: int  # inherited from the TaskCommand for freshness checks


def wrap_angle(angle: float) -> float:
    """Wrap an angle to the half-open range [-pi, pi)."""
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _param(cmd: TaskCommand, key: str) -> float:
    if key not in cmd.params:
        raise MalformedCommandError(f"{cmd.primitive}: missing required param '{key}'")
    return cmd.params[key]


def _positive_param(cmd: TaskCommand, key: str) -> float:
    value = _param(cmd, key)
    if value <= 0:
        raise MalformedCommandError(f"{cmd.primitive}: param '{key}' must be positive, got {value}")
    return value


def _max_curvature_geometry(profile: ScalProfile) -> float:
    """Family curvature bound at top speed — the loosest bound SCAL raises on."""
    return max_curvature_for_speed(profile, profile.core.max_linear_speed)


def _cap_speed_for_curvature(profile: ScalProfile, v_request: float, kappa: float) -> float:
    """Cap a requested speed so holding ``kappa`` stays inside the wheel limit.

    From ``v * (1 + |kappa| * track / 2) <= max_wheel_speed * wheel_radius``,
    i.e. ``v <= 2 * limit / (2 + |kappa| * track)``.
    """
    limit = profile.core.max_wheel_speed * profile.geometry.wheel_radius_m
    v_cap = 2.0 * limit / (2.0 + abs(kappa) * profile.geometry.track_width_m)
    return min(v_request, profile.core.max_linear_speed, v_cap)


def _motion_element(
    profile: ScalProfile,
    solution: TwistSolution,
    duration_us: int,
    source: str,
    issued_us: int,
) -> ChassisCommand:
    targets = {
        role: ActuatorTarget(WHEEL_SPEED, speed)
        for role, speed in solution.wheel_speeds.items()
    }
    targets.update(
        {
            role: ActuatorTarget(STEER_ANGLE, angle)
            for role, angle in solution.steering_angles.items()
        }
    )
    return ChassisCommand(
        targets=targets, duration_us=duration_us, source=source, issued_us=issued_us
    )


def _blade_element(
    on: bool,
    speed: float,
    issued_us: int,
    source: str,
) -> ChassisCommand:
    command_type = BLADE_ON if on else BLADE_OFF
    return ChassisCommand(
        targets={ROLE_BLADE: ActuatorTarget(command_type, speed)},
        duration_us=0,
        source=source,
        issued_us=issued_us,
    )


def _rotate_element(
    profile: ScalProfile,
    phi: float,
    rotate_nominal: float,
    source: str,
    issued_us: int,
) -> ChassisCommand:
    omega = math.copysign(rotate_nominal, phi)
    duration_us = round(abs(phi) / rotate_nominal * 1e6)
    solution = solve_twist(profile, 0.0, omega)
    return _motion_element(profile, solution, duration_us, source, issued_us)


def _ackermann_move_stream(
    profile: ScalProfile,
    context: Pose2D,
    x: float,
    y: float,
    theta: float,
    drive_nominal: float,
    source_prefix: str,
    issued_us: int,
) -> list[ChassisCommand]:
    """Arc-to-point translation: exact landing on the target position.

    The arc's curvature ``kappa = 2 * dy / dist^2`` sends the arc through the
    target (algebraically: with ``phi = bearing``, end pose is
    ``(sin(2 phi)/kappa, (1 - cos(2 phi))/kappa) = (dx, dy)``). The final
    heading is the arc tangent ``2 * phi``; the residual to ``theta`` is
    accepted and documented in the module docstring.
    """
    dx_f, dy_f = x - context.x, y - context.y
    cos_h, sin_h = math.cos(context.theta), math.sin(context.theta)
    dx = cos_h * dx_f + sin_h * dy_f
    dy = -sin_h * dx_f + cos_h * dy_f
    dist = math.hypot(dx, dy)

    if dist <= _ANGLE_EPS:
        heading_residual = abs(wrap_angle(theta - context.theta))
        if heading_residual > 1e-6:
            raise InfeasibleCommandError(
                f"{profile.model}: pose-only MoveTo needs an in-place rotation, "
                "which Ackermann chassis cannot perform"
            )
        return []
    if dx <= 0.0:
        raise InfeasibleCommandError(
            f"{profile.model}: MoveTo target is behind or abeam the axle "
            f"(body dx={dx:.4f}); Ackermann chassis cannot translate onto it"
        )

    v = min(drive_nominal, profile.core.max_linear_speed)
    if abs(dy) <= _ANGLE_EPS:
        solution = solve_twist(profile, v, 0.0)
        duration_us = round(dist / v * 1e6)
        return [
            _motion_element(profile, solution, duration_us, f"{source_prefix}:drive", issued_us)
        ]

    bearing = math.atan2(dy, dx)
    kappa = 2.0 * dy / (dist * dist)
    if abs(kappa) > _max_curvature_geometry(profile):
        raise InfeasibleCommandError(
            f"{profile.model}: MoveTo needs curvature {abs(kappa):.4f} 1/m, beyond "
            f"the chassis bound {_max_curvature_geometry(profile):.4f}"
        )
    v = _cap_speed_for_curvature(profile, v, kappa)
    arc_length = 2.0 * bearing / kappa
    duration_us = round(arc_length / v * 1e6)
    solution = solve_twist(profile, v, v * kappa)
    return [_motion_element(profile, solution, duration_us, f"{source_prefix}:arc", issued_us)]


def _move_to_stream(
    profile: ScalProfile,
    context: Pose2D,
    x: float,
    y: float,
    theta: float,
    drive_nominal: float,
    rotate_nominal: float,
    source_prefix: str,
    issued_us: int,
) -> list[ChassisCommand]:
    """Rotate-drive-rotate decomposition (differential and hybrid families)."""
    dx_f, dy_f = x - context.x, y - context.y
    cos_h, sin_h = math.cos(context.theta), math.sin(context.theta)
    dx = cos_h * dx_f + sin_h * dy_f
    dy = -sin_h * dx_f + cos_h * dy_f

    bearing = math.atan2(dy, dx)
    dist = math.hypot(dx, dy)
    phi_first = wrap_angle(bearing)
    phi_last = wrap_angle(wrap_angle(theta - context.theta) - phi_first)

    geometry = profile.geometry
    spin = geometry.max_spin_rad_s
    if spin is None:  # guarded by ScalProfile validation
        raise ValueError(f"{profile.model}: differential/hybrid chassis without spin bound")
    omega_rot = min(rotate_nominal, spin)
    v_drive = min(drive_nominal, profile.core.max_linear_speed)

    elements: list[ChassisCommand] = []
    if abs(phi_first) > _ANGLE_EPS:
        elements.append(
            _rotate_element(profile, phi_first, omega_rot, f"{source_prefix}:rotate_in", issued_us)
        )
    if dist > _SPEED_EPS:
        solution = solve_twist(profile, v_drive, 0.0)
        duration_us = round(dist / v_drive * 1e6)
        elements.append(
            _motion_element(profile, solution, duration_us, f"{source_prefix}:drive", issued_us)
        )
    if abs(phi_last) > _ANGLE_EPS:
        elements.append(
            _rotate_element(profile, phi_last, omega_rot, f"{source_prefix}:rotate_out", issued_us)
        )
    return elements


def _translate_move_to(
    cmd: TaskCommand,
    profile: ScalProfile,
    context: Pose2D,
) -> list[ChassisCommand]:
    x = _param(cmd, "x")
    y = _param(cmd, "y")
    theta = _param(cmd, "theta")
    if profile.kinematics is Kinematics.ACKERMANN:
        return _ackermann_move_stream(
            profile, context, x, y, theta, NOMINAL_DRIVE_MPS, "MoveTo", cmd.issued_us
        )
    return _move_to_stream(
        profile,
        context,
        x,
        y,
        theta,
        NOMINAL_DRIVE_MPS,
        NOMINAL_ROTATE_RAD_S,
        "MoveTo",
        cmd.issued_us,
    )


def _translate_follow_path(
    cmd: TaskCommand,
    profile: ScalProfile,
    context: Pose2D,
) -> list[ChassisCommand]:
    del context  # the chain is expressed in the chassis start frame
    n_segments = _param(cmd, "n_segments")
    n = int(n_segments)
    if n != n_segments or not 1 <= n <= MAX_PATH_SEGMENTS:
        raise MalformedCommandError(
            f"FollowPath: n_segments must be an integer in [1, {MAX_PATH_SEGMENTS}]"
        )

    elements: list[ChassisCommand] = []
    for i in range(n):
        seg_len = _positive_param(cmd, f"seg{i}_len")
        kappa = _param(cmd, f"seg{i}_curv")
        speed = cmd.params.get(f"seg{i}_speed", NOMINAL_DRIVE_MPS)
        if speed <= 0:
            raise MalformedCommandError(f"FollowPath: seg{i}_speed must be positive")
        if (
            profile.kinematics is Kinematics.ACKERMANN
            and abs(kappa) > _max_curvature_geometry(profile)
        ):
            raise InfeasibleCommandError(
                f"{profile.model}: FollowPath segment {i} curvature {abs(kappa):.4f} 1/m "
                f"exceeds the chassis bound {_max_curvature_geometry(profile):.4f}"
            )
        v = _cap_speed_for_curvature(profile, min(speed, profile.core.max_linear_speed), kappa)
        if v <= _SPEED_EPS:
            raise InfeasibleCommandError(
                f"{profile.model}: FollowPath segment {i} curvature {abs(kappa):.4f} 1/m "
                "caps the speed to zero"
            )
        solution = solve_twist(profile, v, v * kappa)
        duration_us = round(seg_len / v * 1e6)
        elements.append(
            _motion_element(profile, solution, duration_us, f"FollowPath:seg{i}", cmd.issued_us)
        )
    return elements


def _translate_set_blade(
    cmd: TaskCommand,
    profile: ScalProfile,
    context: Pose2D,
) -> list[ChassisCommand]:
    del context
    if ROLE_BLADE not in profile.core.actuators:
        raise InfeasibleCommandError(f"{profile.model}: chassis has no blade actuator")
    enabled = _param(cmd, "enabled")
    if enabled not in (0.0, 1.0):
        raise MalformedCommandError(f"SetBlade: 'enabled' must be 0.0 or 1.0, got {enabled}")
    blade_max = profile.geometry.blade_max_speed_rad_s
    if blade_max is None:  # guarded by ScalProfile validation
        raise ValueError(f"{profile.model}: blade actuator without blade_max_speed_rad_s")
    if enabled == 0.0:
        return [_blade_element(False, 0.0, cmd.issued_us, "SetBlade")]
    speed = _param(cmd, "speed")
    if speed < 0:
        raise MalformedCommandError(f"SetBlade: 'speed' must be non-negative, got {speed}")
    if speed > blade_max:
        raise InfeasibleCommandError(
            f"{profile.model}: blade speed {speed:.1f} rad/s exceeds the actuator "
            f"limit {blade_max:.1f} rad/s"
        )
    return [_blade_element(True, speed, cmd.issued_us, "SetBlade")]


def _translate_dock(
    cmd: TaskCommand,
    profile: ScalProfile,
    context: Pose2D,
) -> list[ChassisCommand]:
    x = _param(cmd, "x")
    y = _param(cmd, "y")
    theta = _param(cmd, "theta")
    drive_nominal = NOMINAL_DRIVE_MPS * DOCK_SPEED_FRACTION
    rotate_nominal = NOMINAL_ROTATE_RAD_S * DOCK_SPEED_FRACTION
    if profile.kinematics is Kinematics.ACKERMANN:
        elements = _ackermann_move_stream(
            profile, context, x, y, theta, drive_nominal, "Dock", cmd.issued_us
        )
    else:
        elements = _move_to_stream(
            profile,
            context,
            x,
            y,
            theta,
            drive_nominal,
            rotate_nominal,
            "Dock",
            cmd.issued_us,
        )
    if ROLE_BLADE in profile.core.actuators:
        # Safety semantics: docking always stops the blade.
        elements.append(_blade_element(False, 0.0, cmd.issued_us, "Dock:blade_off"))
    return elements


_HANDLERS = {
    PRIMITIVE_MOVE_TO: _translate_move_to,
    PRIMITIVE_FOLLOW_PATH: _translate_follow_path,
    PRIMITIVE_SET_BLADE: _translate_set_blade,
    PRIMITIVE_DOCK: _translate_dock,
}


class SCALTranslator:
    """Translates task primitives into chassis-specific command streams.

    Stateless by design: every call is pure, so streams are reproducible and
    the governor can re-derive them. ``InstrumentedTranslator`` wraps this
    class to capture per-command latency for the bench harness.
    """

    def translate(
        self,
        cmd: TaskCommand,
        profile: ScalProfile,
        context: Pose2D | None = None,
    ) -> list[ChassisCommand]:
        ctx = context if context is not None else Pose2D()
        handler = _HANDLERS.get(cmd.primitive)
        if handler is None:
            raise MalformedCommandError(
                f"unknown primitive {cmd.primitive!r}; expected one of {sorted(_HANDLERS)}"
            )
        return handler(cmd, profile, ctx)

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
        """Raw twist-level translation: the core semantic operation of SCAL."""
        solution = solve_twist(profile, v, omega)
        return _motion_element(profile, solution, duration_us, source, issued_us)
