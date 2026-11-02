"""SCAL: Semantic Capability Abstraction Layer.

Public API: chassis profiles, kinematic solvers, the task-primitive
translator, latency instrumentation, and the deterministic benchmark
corpus. Each module's docstring carries its contract.
"""

from aegiscore.scal.corpus import CORPUS_SEED, CORPUS_SIZE, Trajectory, build_corpus
from aegiscore.scal.errors import (
    InfeasibleCommandError,
    MalformedCommandError,
    ScalError,
)
from aegiscore.scal.instrumentation import (
    InstrumentedTranslator,
    LatencyRecorder,
    LatencyReport,
    LatencySample,
)
from aegiscore.scal.kinematics import (
    TwistSolution,
    forward_twist,
    is_admissible,
    max_curvature_for_speed,
    solve_twist,
)
from aegiscore.scal.profiles import (
    REFERENCE_PROFILES,
    ROLE_BLADE,
    ROLE_FRONT_LEFT_WHEEL,
    ROLE_FRONT_RIGHT_WHEEL,
    ROLE_LEFT_WHEEL,
    ROLE_REAR_LEFT_WHEEL,
    ROLE_REAR_RIGHT_WHEEL,
    ROLE_RIGHT_WHEEL,
    ROLE_STEER_LEFT,
    ROLE_STEER_RIGHT,
    ChassisGeometry,
    ScalProfile,
)
from aegiscore.scal.translator import (
    BLADE_OFF,
    BLADE_ON,
    PRIMITIVE_DOCK,
    PRIMITIVE_FOLLOW_PATH,
    PRIMITIVE_MOVE_TO,
    PRIMITIVE_SET_BLADE,
    STEER_ANGLE,
    WHEEL_SPEED,
    ActuatorTarget,
    ChassisCommand,
    Pose2D,
    SCALTranslator,
    wrap_angle,
)

__all__ = [
    "BLADE_OFF",
    "BLADE_ON",
    "CORPUS_SEED",
    "CORPUS_SIZE",
    "ChassisCommand",
    "ChassisGeometry",
    "InfeasibleCommandError",
    "InstrumentedTranslator",
    "MalformedCommandError",
    "PRIMITIVE_DOCK",
    "PRIMITIVE_FOLLOW_PATH",
    "PRIMITIVE_MOVE_TO",
    "PRIMITIVE_SET_BLADE",
    "Pose2D",
    "REFERENCE_PROFILES",
    "ROLE_BLADE",
    "ROLE_FRONT_LEFT_WHEEL",
    "ROLE_FRONT_RIGHT_WHEEL",
    "ROLE_LEFT_WHEEL",
    "ROLE_REAR_LEFT_WHEEL",
    "ROLE_REAR_RIGHT_WHEEL",
    "ROLE_RIGHT_WHEEL",
    "ROLE_STEER_LEFT",
    "ROLE_STEER_RIGHT",
    "ScalError",
    "SCALTranslator",
    "STEER_ANGLE",
    "ScalProfile",
    "Trajectory",
    "TwistSolution",
    "WHEEL_SPEED",
    "ActuatorTarget",
    "LatencyRecorder",
    "LatencyReport",
    "LatencySample",
    "build_corpus",
    "forward_twist",
    "is_admissible",
    "max_curvature_for_speed",
    "solve_twist",
    "wrap_angle",
]
