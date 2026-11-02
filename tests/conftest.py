"""Shared builders for governor tests: profiles, states, commands, governors."""

from __future__ import annotations

import pytest

from aegiscore.core.model import ChassisProfile, Kinematics, RobotState, TaskCommand
from aegiscore.governor import GovernorConfig, GovernorCore


@pytest.fixture
def profile() -> ChassisProfile:
    return ChassisProfile(
        model="sim-mower-diff",
        kinematics=Kinematics.DIFFERENTIAL,
        max_linear_speed=1.0,
        max_accel=1.5,
        max_wheel_speed=20.0,
        blade_inertia_kg_m2=0.02,
        actuators={"drive": "act.drive", "blade": "act.blade", "brake": "act.brake"},
    )


@pytest.fixture
def make_state():
    """Builder for RobotState with sim-mower defaults; ages are relative to now_us."""

    def _make(
        now_us: int = 0,
        *,
        v: float = 0.0,
        w: float = 0.0,
        obstacle: float | None = None,
        heartbeat_age_us: float = 0.0,
        brake: float = 1.0,
        blade: float = 0.0,
        pose: dict[str, float] | None = None,
    ) -> RobotState:
        return RobotState(
            timestamp_us=now_us,
            pose=pose if pose is not None else {"x": 0.0, "y": 0.0, "theta": 0.0},
            linear_velocity=v,
            angular_velocity=w,
            actuator_states={"act.drive": v, "act.blade": blade, "act.brake": brake},
            last_heartbeat_us=now_us - int(heartbeat_age_us),
            nearest_obstacle_m=obstacle,
        )

    return _make


@pytest.fixture
def make_cmd():
    """Builder for TaskCommand; target_speed=None omits the parameter (malformed)."""

    def _make(
        primitive: str = "MoveTo",
        *,
        target_speed: float | None = 0.5,
        issued_us: int = 0,
        **extra: float,
    ) -> TaskCommand:
        params: dict[str, float] = {}
        if target_speed is not None:
            params["target_speed"] = target_speed
        params.update(extra)
        return TaskCommand(primitive=primitive, params=params, issued_us=issued_us)

    return _make


@pytest.fixture
def make_governor(profile):
    """Builder for a GovernorCore on the sim profile with config overrides."""

    def _make(**config) -> GovernorCore:
        return GovernorCore(profile, GovernorConfig(**config))

    return _make
