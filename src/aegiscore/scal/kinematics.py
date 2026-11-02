"""Per-family kinematic solvers: the mathematical core of SCAL.

Each solver maps a body twist (``v`` m/s, ``omega`` rad/s) to per-actuator
targets and back:

- DIFFERENTIAL: unicycle model, two driven wheels.
- ACKERMANN: inverse bicycle model, driven rear axle + steered front wheels.
- HYBRID: multi-motor skid distribution over >= 4 independently driven wheels.

All functions are pure: no clocks, no I/O, no global state. ``admissible``
defines the motion envelope (task-space box intersected with the actuator
region); ``solve_twist`` refuses twists outside it rather than saturating —
limit enforcement is the governor's job, and silent saturation here would
hide envelope bugs instead of surfacing them.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from aegiscore.scal.errors import InfeasibleCommandError
from aegiscore.scal.profiles import (
    ROLE_LEFT_WHEEL,
    ROLE_REAR_LEFT_WHEEL,
    ROLE_REAR_RIGHT_WHEEL,
    ROLE_RIGHT_WHEEL,
    ROLE_STEER_LEFT,
    ROLE_STEER_RIGHT,
    ScalProfile,
)

# Twists with |omega| below this are treated as straight travel, avoiding the
# division by omega in the curvature computation for numerically-zero spins.
_STRAIGHT_EPS = 1e-9


@dataclass(frozen=True)
class TwistSolution:
    """Per-actuator targets for one body twist, in chassis coordinates.

    ``wheel_speeds`` are signed wheel angular speeds in rad/s keyed by wheel
    role; ``steering_angles`` are signed steer angles in rad (empty for
    non-steered families).
    """

    wheel_speeds: dict[str, float]
    steering_angles: dict[str, float]


def _wheel_linear_limit(profile: ScalProfile) -> float:
    """Fastest wheel-surface speed the actuators can produce, in m/s."""
    return profile.core.max_wheel_speed * profile.geometry.wheel_radius_m


def _validate_offsets(profile: ScalProfile) -> dict[str, float]:
    offsets = profile.geometry.wheel_lateral_offsets_m
    if offsets is None:  # guarded by ScalProfile validation
        raise ValueError(f"{profile.model}: hybrid chassis without wheel lateral offsets")
    return offsets


# --- Differential (unicycle) -----------------------------------------------


def _solve_differential(profile: ScalProfile, v: float, omega: float) -> TwistSolution:
    half_track = profile.geometry.track_width_m / 2.0
    radius = profile.geometry.wheel_radius_m
    left = (v - omega * half_track) / radius
    right = (v + omega * half_track) / radius
    return TwistSolution(
        wheel_speeds={ROLE_LEFT_WHEEL: left, ROLE_RIGHT_WHEEL: right},
        steering_angles={},
    )


def _forward_differential(profile: ScalProfile, solution: TwistSolution) -> tuple[float, float]:
    radius = profile.geometry.wheel_radius_m
    track = profile.geometry.track_width_m
    left = solution.wheel_speeds[ROLE_LEFT_WHEEL]
    right = solution.wheel_speeds[ROLE_RIGHT_WHEEL]
    v = radius * (right + left) / 2.0
    omega = radius * (right - left) / track
    return v, omega


def _admissible_differential(profile: ScalProfile, v: float, omega: float) -> bool:
    if abs(v) > profile.core.max_linear_speed:
        return False
    spin = profile.geometry.max_spin_rad_s
    if spin is None or abs(omega) > spin:
        return False
    limit = _wheel_linear_limit(profile)
    half_track = profile.geometry.track_width_m / 2.0
    return abs(v - omega * half_track) <= limit and abs(v + omega * half_track) <= limit


def _max_curvature_differential(profile: ScalProfile, v: float) -> float:
    """Largest |kappa| keeping the wheels inside the actuator limit at speed v.

    From ``v * (1 + |kappa| * track / 2) <= limit``. Callers must pass
    ``v > 0``; at ``v -> 0`` the curvature budget grows without bound.
    """
    return 2.0 * max(_wheel_linear_limit(profile) / v - 1.0, 0.0) / profile.geometry.track_width_m


# --- Ackermann (inverse bicycle) --------------------------------------------


def _ackermann_kappa_max(profile: ScalProfile) -> float:
    """Curvature bound implied by the max per-wheel steer angle.

    The inner wheel reaches ``max_steer_rad`` first; from
    ``tan(max_steer) = wheelbase / (R_center - track / 2)``.
    """
    wheelbase = profile.geometry.wheelbase_m
    steer = profile.geometry.max_steer_rad
    if wheelbase is None or steer is None:  # guarded by ScalProfile validation
        raise ValueError(f"{profile.model}: Ackermann chassis without steering geometry")
    radius_center = wheelbase / math.tan(steer) + profile.geometry.track_width_m / 2.0
    return 1.0 / radius_center


def _solve_ackermann(profile: ScalProfile, v: float, omega: float) -> TwistSolution:
    geometry = profile.geometry
    radius = geometry.wheel_radius_m
    half_track = geometry.track_width_m / 2.0

    if abs(omega) <= _STRAIGHT_EPS:
        wheel = v / radius
        return TwistSolution(
            wheel_speeds={
                ROLE_REAR_LEFT_WHEEL: wheel,
                ROLE_REAR_RIGHT_WHEEL: wheel,
            },
            steering_angles={ROLE_STEER_LEFT: 0.0, ROLE_STEER_RIGHT: 0.0},
        )
    if abs(v) <= _STRAIGHT_EPS:
        raise InfeasibleCommandError(
            f"{profile.model}: Ackermann chassis cannot rotate in place (omega={omega})"
        )

    # Rigid rear axle: the rear wheels see the same distribution as a unicycle.
    left = (v - omega * half_track) / radius
    right = (v + omega * half_track) / radius

    # Ackermann steering: each front wheel points at the true turn center,
    # located at signed distance R_c = v / omega from the centerline.
    radius_center = v / omega
    radius_left = radius_center - half_track
    radius_right = radius_center + half_track
    if radius_left == 0.0 or radius_right == 0.0:
        raise InfeasibleCommandError(
            f"{profile.model}: turn radius passes through a wheel (kappa={omega / v:.4f})"
        )
    wheelbase = geometry.wheelbase_m
    if wheelbase is None:  # guarded by ScalProfile validation
        raise ValueError(f"{profile.model}: Ackermann chassis without wheelbase")
    steer_left = math.atan(wheelbase / radius_left)
    steer_right = math.atan(wheelbase / radius_right)

    return TwistSolution(
        wheel_speeds={ROLE_REAR_LEFT_WHEEL: left, ROLE_REAR_RIGHT_WHEEL: right},
        steering_angles={ROLE_STEER_LEFT: steer_left, ROLE_STEER_RIGHT: steer_right},
    )


def _forward_ackermann(profile: ScalProfile, solution: TwistSolution) -> tuple[float, float]:
    radius = profile.geometry.wheel_radius_m
    track = profile.geometry.track_width_m
    left = solution.wheel_speeds[ROLE_REAR_LEFT_WHEEL]
    right = solution.wheel_speeds[ROLE_REAR_RIGHT_WHEEL]
    v = radius * (right + left) / 2.0
    omega = radius * (right - left) / track
    return v, omega


def _admissible_ackermann(profile: ScalProfile, v: float, omega: float) -> bool:
    if abs(v) > profile.core.max_linear_speed:
        return False
    if abs(omega) <= _STRAIGHT_EPS:
        return True
    if abs(v) <= _STRAIGHT_EPS:
        return False  # in-place rotation is kinematically impossible
    kappa = omega / v
    if abs(kappa) > _ackermann_kappa_max(profile):
        return False
    limit = _wheel_linear_limit(profile)
    half_track = profile.geometry.track_width_m / 2.0
    return abs(v - omega * half_track) <= limit and abs(v + omega * half_track) <= limit


def _max_curvature_ackermann(profile: ScalProfile, v: float) -> float:
    """min of the steer-angle bound and the rear-wheel actuator bound at v."""
    kappa_max = _ackermann_kappa_max(profile)
    if v <= _STRAIGHT_EPS:
        return kappa_max
    wheel_bound = 2.0 * max(_wheel_linear_limit(profile) / v - 1.0, 0.0)
    return min(kappa_max, wheel_bound / profile.geometry.track_width_m)


# --- Hybrid multi-motor (skid distribution) ---------------------------------


def _solve_hybrid(profile: ScalProfile, v: float, omega: float) -> TwistSolution:
    offsets = _validate_offsets(profile)
    radius = profile.geometry.wheel_radius_m
    # Point-velocity model: the body point at lateral offset y moves at
    # (v - omega * y) along the chassis heading; each wheel tracks that speed.
    speeds = {role: (v - omega * y) / radius for role, y in offsets.items()}
    return TwistSolution(wheel_speeds=speeds, steering_angles={})


def _forward_hybrid(profile: ScalProfile, solution: TwistSolution) -> tuple[float, float]:
    offsets = _validate_offsets(profile)
    radius = profile.geometry.wheel_radius_m
    ys = [offsets[role] for role in offsets]
    speeds = [solution.wheel_speeds[role] for role in offsets]

    # Least-squares fit of omega_wheel * r = v - omega * y over all wheels;
    # exact for our own solutions, tolerant of asymmetric configurations.
    n = float(len(ys))
    sy = sum(ys)
    syy = sum(y * y for y in ys)
    somega = sum(speeds)
    syomega = sum(y * w for y, w in zip(ys, speeds, strict=False))
    det = n * syy - sy * sy
    if det <= 1e-12:
        raise ValueError(f"{profile.model}: degenerate wheel lateral offsets (no variance)")
    v = radius * (syy * somega - sy * syomega) / det
    omega = radius * (sy * somega - n * syomega) / det
    return v, omega


def _admissible_hybrid(profile: ScalProfile, v: float, omega: float) -> bool:
    if abs(v) > profile.core.max_linear_speed:
        return False
    spin = profile.geometry.max_spin_rad_s
    if spin is None or abs(omega) > spin:
        return False
    limit = _wheel_linear_limit(profile)
    offsets = _validate_offsets(profile)
    return all(abs(v - omega * y) <= limit for y in offsets.values())


def _max_curvature_hybrid(profile: ScalProfile, v: float) -> float:
    return _max_curvature_differential(profile, v)


# --- Registry and module-level dispatch -------------------------------------


@dataclass(frozen=True)
class KinematicSolver:
    """The four operations every kinematic family must provide."""

    solve: Callable[[ScalProfile, float, float], TwistSolution]
    forward: Callable[[ScalProfile, TwistSolution], tuple[float, float]]
    admissible: Callable[[ScalProfile, float, float], bool]
    max_curvature: Callable[[ScalProfile, float], float]


_SOLVERS: dict[str, KinematicSolver] = {
    "DIFFERENTIAL": KinematicSolver(
        solve=_solve_differential,
        forward=_forward_differential,
        admissible=_admissible_differential,
        max_curvature=_max_curvature_differential,
    ),
    "ACKERMANN": KinematicSolver(
        solve=_solve_ackermann,
        forward=_forward_ackermann,
        admissible=_admissible_ackermann,
        max_curvature=_max_curvature_ackermann,
    ),
    "HYBRID": KinematicSolver(
        solve=_solve_hybrid,
        forward=_forward_hybrid,
        admissible=_admissible_hybrid,
        max_curvature=_max_curvature_hybrid,
    ),
}


def _solver_for(profile: ScalProfile) -> KinematicSolver:
    # Enum `.name` (DIFFERENTIAL/ACKERMANN/HYBRID) keys the registry; `.value`
    # is the wire spelling ("differential"/"hybrid_multi_motor") and does not.
    return _SOLVERS[profile.kinematics.name]


def solve_twist(profile: ScalProfile, v: float, omega: float) -> TwistSolution:
    """Translate a body twist to per-actuator targets, refusing infeasible twists.

    Raises ``InfeasibleCommandError`` when the twist leaves the profile's
    envelope — never saturates silently.
    """
    solver = _solver_for(profile)
    if not solver.admissible(profile, v, omega):
        raise InfeasibleCommandError(
            f"{profile.model}: twist (v={v:.4f} m/s, omega={omega:.4f} rad/s) "
            "is outside the motion envelope"
        )
    return solver.solve(profile, v, omega)


def forward_twist(profile: ScalProfile, solution: TwistSolution) -> tuple[float, float]:
    """Forward kinematics: per-actuator targets back to the body twist."""
    return _solver_for(profile).forward(profile, solution)


def is_admissible(profile: ScalProfile, v: float, omega: float) -> bool:
    """True when the twist lies inside the profile's motion envelope."""
    return _solver_for(profile).admissible(profile, v, omega)


def max_curvature_for_speed(profile: ScalProfile, v: float) -> float:
    """Largest |kappa| the profile can hold at body speed ``v`` (v > 0)."""
    return _solver_for(profile).max_curvature(profile, v)
