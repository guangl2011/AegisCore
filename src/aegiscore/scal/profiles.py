"""Chassis profiles for SCAL: geometry, validation, and reference chassis.

The core ``ChassisProfile`` (``aegiscore.core.model``) declares kinematics,
the actuator map, and physical limits. The kinematic solvers additionally
need physical geometry (wheel radius, track, wheelbase, steer range), so
``ScalProfile`` bundles a core profile with its ``ChassisGeometry`` and
validates that the two are mutually consistent.

``REFERENCE_PROFILES`` ships one validated chassis per kinematic family so
the translator, the bench harness, and the trajectory corpus all measure
the same three chassis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aegiscore.core.model import ChassisProfile, Kinematics

# Logical actuator roles. Profiles map role -> actuator id in
# ``ChassisProfile.actuators``; solvers and the translator key targets by role.
ROLE_LEFT_WHEEL = "left_wheel"
ROLE_RIGHT_WHEEL = "right_wheel"
ROLE_FRONT_LEFT_WHEEL = "front_left_wheel"
ROLE_FRONT_RIGHT_WHEEL = "front_right_wheel"
ROLE_REAR_LEFT_WHEEL = "rear_left_wheel"
ROLE_REAR_RIGHT_WHEEL = "rear_right_wheel"
ROLE_STEER_LEFT = "steer_left"
ROLE_STEER_RIGHT = "steer_right"
ROLE_BLADE = "blade"

_DIFF_WHEEL_ROLES = (ROLE_LEFT_WHEEL, ROLE_RIGHT_WHEEL)
_ACK_WHEEL_ROLES = (ROLE_REAR_LEFT_WHEEL, ROLE_REAR_RIGHT_WHEEL)
_ACK_STEER_ROLES = (ROLE_STEER_LEFT, ROLE_STEER_RIGHT)
_HYBRID_WHEEL_ROLES = (
    ROLE_FRONT_LEFT_WHEEL,
    ROLE_FRONT_RIGHT_WHEEL,
    ROLE_REAR_LEFT_WHEEL,
    ROLE_REAR_RIGHT_WHEEL,
)


@dataclass(frozen=True)
class ChassisGeometry:
    """Physical geometry the kinematic solvers need, beyond the core limits.

    ``wheel_lateral_offsets_m`` (hybrid only) maps each wheel role to its
    signed lateral offset from the chassis centerline (left positive).
    ``max_spin_rad_s`` (differential/hybrid only) bounds the task-space
    spin rate; the actuator-implied spin bound must not be smaller.
    """

    wheel_radius_m: float
    track_width_m: float
    wheelbase_m: float | None = None
    max_steer_rad: float | None = None
    max_spin_rad_s: float | None = None
    wheel_lateral_offsets_m: dict[str, float] | None = None
    blade_max_speed_rad_s: float | None = None


@dataclass(frozen=True)
class ScalProfile:
    """A core chassis profile bundled with the geometry its solvers need.

    Construction validates that limits, actuator roles, and geometry are
    mutually consistent, so every downstream solver can assume a coherent
    profile (e.g. the actuators can deliver ``max_linear_speed``).
    """

    core: ChassisProfile
    geometry: ChassisGeometry

    @property
    def model(self) -> str:
        return self.core.model

    @property
    def kinematics(self) -> Kinematics:
        return self.core.kinematics

    def wheel_roles(self) -> frozenset[str]:
        """Actuator roles that are driven wheels for this chassis family."""
        if self.core.kinematics is Kinematics.DIFFERENTIAL:
            return frozenset(_DIFF_WHEEL_ROLES)
        if self.core.kinematics is Kinematics.ACKERMANN:
            return frozenset(_ACK_WHEEL_ROLES)
        return frozenset(_HYBRID_WHEEL_ROLES)

    def blade_role(self) -> str | None:
        """The blade actuator role, or None for bladeless chassis."""
        return ROLE_BLADE if ROLE_BLADE in self.core.actuators else None

    def __post_init__(self) -> None:
        _validate(self.core, self.geometry)


def _require_roles(core: ChassisProfile, required: tuple[str, ...]) -> None:
    missing = [role for role in required if role not in core.actuators]
    if missing:
        raise ValueError(f"{core.model}: missing actuator roles {missing}")


def _validate_spin(core: ChassisProfile, geometry: ChassisGeometry) -> None:
    spin = geometry.max_spin_rad_s
    if spin is None or spin <= 0:
        raise ValueError(f"{core.model}: max_spin_rad_s is required and must be positive")
    actuator_spin = 2.0 * core.max_wheel_speed * geometry.wheel_radius_m / geometry.track_width_m
    if spin > actuator_spin + 1e-12:
        raise ValueError(
            f"{core.model}: max_spin_rad_s {spin} exceeds the actuator-implied "
            f"spin bound {actuator_spin:.4f} rad/s"
        )


def _validate_blade_consistency(core: ChassisProfile, geometry: ChassisGeometry) -> None:
    has_blade_role = ROLE_BLADE in core.actuators
    if has_blade_role != (core.blade_inertia_kg_m2 is not None):
        raise ValueError(
            f"{core.model}: the '{ROLE_BLADE}' actuator role and blade_inertia_kg_m2 "
            "must be declared together"
        )
    if has_blade_role != (geometry.blade_max_speed_rad_s is not None):
        raise ValueError(
            f"{core.model}: blade_max_speed_rad_s is required exactly when a blade is present"
        )


def _validate(core: ChassisProfile, geometry: ChassisGeometry) -> None:
    if core.max_linear_speed <= 0 or core.max_accel <= 0 or core.max_wheel_speed <= 0:
        raise ValueError(f"{core.model}: profile limits must be positive")
    if geometry.wheel_radius_m <= 0 or geometry.track_width_m <= 0:
        raise ValueError(f"{core.model}: wheel radius and track width must be positive")

    wheel_limit_m_s = core.max_wheel_speed * geometry.wheel_radius_m
    if wheel_limit_m_s < core.max_linear_speed:
        raise ValueError(
            f"{core.model}: wheel actuators cap out at {wheel_limit_m_s:.4f} m/s, "
            f"below max_linear_speed {core.max_linear_speed}"
        )

    if core.kinematics is Kinematics.DIFFERENTIAL:
        _require_roles(core, _DIFF_WHEEL_ROLES)
        _validate_spin(core, geometry)
    elif core.kinematics is Kinematics.ACKERMANN:
        _require_roles(core, _ACK_WHEEL_ROLES + _ACK_STEER_ROLES)
        if geometry.wheelbase_m is None or geometry.wheelbase_m <= 0:
            raise ValueError(f"{core.model}: wheelbase_m is required and must be positive")
        if geometry.max_steer_rad is None or not 0 < geometry.max_steer_rad < math.pi / 2:
            raise ValueError(f"{core.model}: max_steer_rad must lie in (0, pi/2)")
        if geometry.max_spin_rad_s is not None:
            raise ValueError(f"{core.model}: max_spin_rad_s does not apply to Ackermann chassis")
    elif core.kinematics is Kinematics.HYBRID:
        _require_roles(core, _HYBRID_WHEEL_ROLES)
        _validate_spin(core, geometry)
        offsets = geometry.wheel_lateral_offsets_m
        if offsets is None or set(offsets) != set(_HYBRID_WHEEL_ROLES):
            raise ValueError(
                f"{core.model}: wheel_lateral_offsets_m must map exactly the hybrid wheel roles"
            )
        for role in (ROLE_FRONT_LEFT_WHEEL, ROLE_REAR_LEFT_WHEEL):
            if offsets[role] <= 0:
                raise ValueError(f"{core.model}: left wheel role '{role}' needs a positive offset")
        for role in (ROLE_FRONT_RIGHT_WHEEL, ROLE_REAR_RIGHT_WHEEL):
            if offsets[role] >= 0:
                raise ValueError(f"{core.model}: right wheel role '{role}' needs a negative offset")
        half_track = geometry.track_width_m / 2.0
        if any(abs(abs(y) - half_track) > 1e-9 for y in offsets.values()):
            raise ValueError(
                f"{core.model}: wheel lateral offsets must match the declared track width"
            )
    else:
        raise ValueError(f"{core.model}: unknown kinematics {core.kinematics!r}")

    _validate_blade_consistency(core, geometry)


def _diff_mower() -> ScalProfile:
    return ScalProfile(
        core=ChassisProfile(
            model="ref-diff-mower",
            kinematics=Kinematics.DIFFERENTIAL,
            max_linear_speed=1.5,
            max_accel=1.0,
            max_wheel_speed=20.0,
            blade_inertia_kg_m2=0.08,
            actuators={
                ROLE_LEFT_WHEEL: "act-lw",
                ROLE_RIGHT_WHEEL: "act-rw",
                ROLE_BLADE: "act-blade",
            },
        ),
        geometry=ChassisGeometry(
            wheel_radius_m=0.1,
            track_width_m=0.44,
            max_spin_rad_s=3.0,
            blade_max_speed_rad_s=300.0,
        ),
    )


def _ackermann_utv() -> ScalProfile:
    return ScalProfile(
        core=ChassisProfile(
            model="ref-ack-utv",
            kinematics=Kinematics.ACKERMANN,
            max_linear_speed=4.0,
            max_accel=2.0,
            max_wheel_speed=32.0,
            blade_inertia_kg_m2=None,
            actuators={
                ROLE_REAR_LEFT_WHEEL: "act-rl",
                ROLE_REAR_RIGHT_WHEEL: "act-rr",
                ROLE_STEER_LEFT: "act-sl",
                ROLE_STEER_RIGHT: "act-sr",
            },
        ),
        geometry=ChassisGeometry(
            wheel_radius_m=0.15,
            track_width_m=1.1,
            wheelbase_m=1.6,
            max_steer_rad=0.5,
        ),
    )


def _hybrid_mower() -> ScalProfile:
    return ScalProfile(
        core=ChassisProfile(
            model="ref-hybrid-mower",
            kinematics=Kinematics.HYBRID,
            max_linear_speed=1.8,
            max_accel=1.5,
            max_wheel_speed=22.0,
            blade_inertia_kg_m2=0.06,
            actuators={
                ROLE_FRONT_LEFT_WHEEL: "act-fl",
                ROLE_FRONT_RIGHT_WHEEL: "act-fr",
                ROLE_REAR_LEFT_WHEEL: "act-rl",
                ROLE_REAR_RIGHT_WHEEL: "act-rr",
                ROLE_BLADE: "act-blade",
            },
        ),
        geometry=ChassisGeometry(
            wheel_radius_m=0.125,
            track_width_m=0.5,
            max_spin_rad_s=2.5,
            wheel_lateral_offsets_m={
                ROLE_FRONT_LEFT_WHEEL: 0.25,
                ROLE_FRONT_RIGHT_WHEEL: -0.25,
                ROLE_REAR_LEFT_WHEEL: 0.25,
                ROLE_REAR_RIGHT_WHEEL: -0.25,
            },
            blade_max_speed_rad_s=280.0,
        ),
    )


#: One validated reference chassis per kinematic family, keyed by model name.
REFERENCE_PROFILES: dict[str, ScalProfile] = {
    "ref-diff-mower": _diff_mower(),
    "ref-ack-utv": _ackermann_utv(),
    "ref-hybrid-mower": _hybrid_mower(),
}
