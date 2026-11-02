"""Smoke tests: the package imports and the core data model constructs."""

from aegiscore import __version__
from aegiscore.core.model import ChassisProfile, Kinematics


def test_package_imports() -> None:
    assert __version__ == "0.1.0"


def test_chassis_profile_construction() -> None:
    profile = ChassisProfile(
        model="test-mower-diff",
        kinematics=Kinematics.DIFFERENTIAL,
        max_linear_speed=1.0,
        max_accel=0.5,
        max_wheel_speed=10.0,
        blade_inertia_kg_m2=0.05,
        actuators={"left_wheel": "act-lw", "right_wheel": "act-rw"},
    )
    assert profile.kinematics is Kinematics.DIFFERENTIAL
    assert profile.actuators["left_wheel"] == "act-lw"
