"""Deterministic kinematic chassis simulation — the MVP "hardware" boundary.

One :class:`ChassisSim` instance models one of the three reference chassis as
a pure kinematic unicycle/tricycle: no dynamics, no Gazebo, no wall clock.
Everything is a function of the call sequence:

- **Fixed timestep** — ``integrate`` advances exactly ``dt_us`` of simulation
  time per call; the bench harness drives one governor cycle per step.
- **Seeded scenarios** — the simulator itself draws no randomness; scenario
  construction (fault-onset cycles) is sampled by the harness from a seeded
  ``random.Random``. Same inputs therefore produce identical outputs.
- **The governor is the only actuator-command writer** — the simulator never
  self-motivates: it integrates the twist the admitted command implies, or
  stands still. An executed twist that leaves the profile's motion envelope is
  recorded as a :class:`KinematicViolation` (and still integrated — the sim
  does what the actuators were told, which is the point of counting).

Euler integration at the default 10 ms step keeps per-step heading change
below ~0.05 rad at the fastest spin, far inside the violation tolerances; pose
fidelity is not gated, twist admissibility is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aegiscore.core.model import ChassisProfile, RobotState
from aegiscore.scal.kinematics import is_admissible
from aegiscore.scal.profiles import ROLE_BLADE, ScalProfile

#: Default bench timestep (10 ms of simulation time per governor cycle).
#: Must stay below the governor's watchdog timeout (20 ms) and heartbeat
#: lease (100 ms) so nominal runs never trip them by construction.
SIM_DT_US = 10_000


@dataclass(frozen=True)
class KinematicViolation:
    """One executed twist outside the chassis motion envelope."""

    step_index: int
    v_mps: float
    omega_rad_s: float
    detail: str


class ChassisSim:
    """Kinematic simulation of one reference chassis under governor control."""

    def __init__(self, profile: ScalProfile, dt_us: int = SIM_DT_US) -> None:
        if dt_us <= 0:
            raise ValueError(f"dt_us must be positive, got {dt_us}")
        self._profile = profile
        self._dt_us = dt_us
        self._dt_s = dt_us / 1_000_000.0
        self._governor_profile = _governor_view(profile)
        self.reset()

    # ------------------------------------------------------------------ API

    @property
    def profile(self) -> ScalProfile:
        return self._profile

    @property
    def dt_us(self) -> int:
        return self._dt_us

    @property
    def governor_profile(self) -> ChassisProfile:
        """The core profile the ``GovernorCore`` for this chassis expects."""
        return self._governor_profile

    @property
    def pose(self) -> tuple[float, float, float]:
        return self._x, self._y, self._theta

    @property
    def velocity(self) -> tuple[float, float]:
        """Current executed body twist (v m/s, omega rad/s)."""
        return self._v, self._omega

    @property
    def steps(self) -> int:
        return self._steps

    @property
    def violations(self) -> tuple[KinematicViolation, ...]:
        return tuple(self._violations)

    def reset(self) -> None:
        """Return the chassis to the origin pose at rest, blade off, no obstacle."""
        self._x = 0.0
        self._y = 0.0
        self._theta = 0.0
        self._v = 0.0
        self._omega = 0.0
        self._blade_speed = 0.0
        self._obstacle_m: float | None = None
        self._steps = 0
        self._violations = []

    def make_state(self, now_us: int) -> RobotState:
        """Snapshot the chassis for one governor cycle.

        The simulated host heartbeats every cycle (``last_heartbeat_us = now``)
        and reports an engaged brake; fault scenarios disturb these through the
        governor's fault channel or :meth:`place_obstacle`, never by lying here.
        """
        gp = self._governor_profile
        actuator_states = {gp.actuators["drive"]: self._v, gp.actuators["brake"]: 1.0}
        blade_id = gp.actuators.get(ROLE_BLADE)
        if blade_id is not None:
            actuator_states[blade_id] = self._blade_speed
        return RobotState(
            timestamp_us=now_us,
            pose={"x": self._x, "y": self._y, "theta": self._theta},
            linear_velocity=self._v,
            angular_velocity=self._omega,
            actuator_states=actuator_states,
            last_heartbeat_us=now_us,
            nearest_obstacle_m=self._obstacle_m,
        )

    def set_blade(self, speed_rad_s: float) -> None:
        """Set the measured blade speed (governor-admitted blade commands only)."""
        self._blade_speed = speed_rad_s

    def place_obstacle(self, distance_m: float | None) -> None:
        """Set the proximity reading (None = no obstacle in view)."""
        self._obstacle_m = distance_m

    def integrate(self, v: float, omega: float) -> None:
        """Execute one body twist for one fixed step, counting any violation."""
        if not is_admissible(self._profile, v, omega):
            self._violations.append(
                KinematicViolation(
                    step_index=self._steps,
                    v_mps=v,
                    omega_rad_s=omega,
                    detail=(
                        f"executed twist (v={v:.4f} m/s, omega={omega:.4f} rad/s) outside "
                        f"the {self._profile.model} motion envelope"
                    ),
                )
            )
        dt = self._dt_s
        self._theta += omega * dt
        self._x += v * math.cos(self._theta) * dt
        self._y += v * math.sin(self._theta) * dt
        self._v = v
        self._omega = omega
        self._steps += 1


def _governor_view(profile: ScalProfile) -> ChassisProfile:
    """Adapt a SCAL profile to the actuator vocabulary the governor requires.

    The governor addresses one ``drive`` actuator (the primary wheel), the
    ``blade`` when fitted, and a ``brake`` whose engaged state the sim always
    reports — braking-authority loss is exercised through the fault-injection
    channel. ``drive_speed`` commands are interpreted by the sim as body-speed
    targets; per-wheel targets remain SCAL's decomposition, so the sim
    integrates body twists and derives wheel consistency via ``is_admissible``.
    """
    core = profile.core
    wheel_role = min(profile.wheel_roles())
    actuators = {"drive": core.actuators[wheel_role], "brake": f"brake.{core.model}"}
    if ROLE_BLADE in core.actuators:
        actuators[ROLE_BLADE] = core.actuators[ROLE_BLADE]
    return ChassisProfile(
        model=core.model,
        kinematics=core.kinematics,
        max_linear_speed=core.max_linear_speed,
        max_accel=core.max_accel,
        max_wheel_speed=core.max_wheel_speed,
        blade_inertia_kg_m2=core.blade_inertia_kg_m2,
        actuators=actuators,
    )
