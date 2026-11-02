"""Shared data model for AegisCore.

Downstream modules (SCAL, governor, gateway, sim, harness) import these types
from here — this module is the single source of truth for the interfaces that
cross component boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kinematics(Enum):
    """Chassis kinematic families supported by SCAL."""

    DIFFERENTIAL = "differential"
    ACKERMANN = "ackermann"
    HYBRID = "hybrid_multi_motor"


class GovMode(Enum):
    """Governor failover ladder, ordered most to least permissive.

    Transitions may only descend the ladder (toward E_STOP) except via the
    explicit operator-authorised re-arm path.
    """

    NOMINAL = "NOMINAL"
    FILTERED = "FILTERED"
    CONSERVATIVE = "CONSERVATIVE"
    HOLD = "HOLD"
    CONTROLLED_STOP = "CONTROLLED_STOP"
    E_STOP = "E_STOP"


@dataclass(frozen=True)
class ChassisProfile:
    """Declarative capability profile for one chassis model.

    A profile declares kinematics, actuator map, and physical limits; SCAL
    consumes it to translate platform-agnostic task primitives into
    chassis-specific command streams.
    """

    model: str
    kinematics: Kinematics
    max_linear_speed: float  # m/s
    max_accel: float  # m/s^2
    max_wheel_speed: float  # rad/s, per actuator
    blade_inertia_kg_m2: float | None  # enables kinetic-energy envelope
    actuators: dict[str, str]  # logical role -> actuator id


@dataclass
class TaskCommand:
    """Platform-agnostic task primitive emitted by operational software.

    Examples of `primitive`: MoveTo, FollowPath, SetBlade, Dock.
    """

    primitive: str
    params: dict[str, float]  # primitive-specific parameters
    issued_us: int  # monotonic microseconds at issue time


@dataclass
class RobotState:
    """Snapshot of chassis state for one governor cycle."""

    timestamp_us: int  # monotonic microseconds
    pose: dict[str, float]  # x, y, theta
    linear_velocity: float  # m/s
    angular_velocity: float  # rad/s
    actuator_states: dict[str, float]  # actuator id -> measured state
    last_heartbeat_us: int  # monotonic microseconds of last host heartbeat
    # Proximity sensor reading (nearest obstacle, metres). None = sensor not
    # fitted; NaN/inf = sensor loss. Consumed by the governor's proximity
    # envelope — additive with a default so existing constructors keep working.
    nearest_obstacle_m: float | None = None


@dataclass
class ActuatorCommand:
    """Chassis-specific command for a single actuator.

    Only the governor core may emit these; everything upstream produces
    TaskCommands.
    """

    actuator_id: str
    command_type: str  # e.g. "wheel_speed", "blade_on", "blade_off"
    value: float
    issued_us: int  # monotonic microseconds


@dataclass
class GovernorDecision:
    """Result of one deterministic supervisor cycle.

    Every cycle appends a decision record to the safety log — admitted
    command, margins, mode — the basis of the 100% deterministic safety
    logging guarantee.
    """

    admitted: ActuatorCommand | None
    mode: GovMode
    margins: dict[str, float]  # constraint name -> remaining margin
    reason: str | None  # set when a command was filtered/rejected
