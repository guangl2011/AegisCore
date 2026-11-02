"""Unit tests for chassis geometry, profile validation, and reference profiles."""

import math

import pytest

from aegiscore.core.model import ChassisProfile, Kinematics
from aegiscore.scal.profiles import (
    REFERENCE_PROFILES,
    ROLE_BLADE,
    ROLE_LEFT_WHEEL,
    ROLE_RIGHT_WHEEL,
    ChassisGeometry,
    ScalProfile,
)
from aegiscore.scal.translator import wrap_angle


def test_three_reference_profiles_cover_all_families() -> None:
    assert set(REFERENCE_PROFILES) == {"ref-diff-mower", "ref-ack-utv", "ref-hybrid-mower"}
    assert [p.kinematics for p in REFERENCE_PROFILES.values()] == [
        Kinematics.DIFFERENTIAL,
        Kinematics.ACKERMANN,
        Kinematics.HYBRID,
    ]


@pytest.mark.parametrize("profile", REFERENCE_PROFILES.values(), ids=lambda p: p.model)
def test_reference_profiles_declare_limits(profile: ScalProfile) -> None:
    core = profile.core
    assert core.max_linear_speed > 0
    assert core.max_accel > 0
    assert core.max_wheel_speed > 0
    assert core.actuators, "profiles must declare an actuator map"


@pytest.mark.parametrize("profile", REFERENCE_PROFILES.values(), ids=lambda p: p.model)
def test_actuators_can_deliver_max_linear_speed(profile: ScalProfile) -> None:
    wheel_surface = profile.core.max_wheel_speed * profile.geometry.wheel_radius_m
    assert wheel_surface >= profile.core.max_linear_speed


@pytest.mark.parametrize("profile", REFERENCE_PROFILES.values(), ids=lambda p: p.model)
def test_blade_declaration_is_consistent(profile: ScalProfile) -> None:
    has_blade = ROLE_BLADE in profile.core.actuators
    assert has_blade == (profile.core.blade_inertia_kg_m2 is not None)
    assert has_blade == (profile.geometry.blade_max_speed_rad_s is not None)


def test_diff_mower_layout() -> None:
    profile = REFERENCE_PROFILES["ref-diff-mower"]
    assert set(profile.core.actuators) == {ROLE_LEFT_WHEEL, ROLE_RIGHT_WHEEL, ROLE_BLADE}
    assert profile.geometry.wheel_lateral_offsets_m is None
    assert profile.geometry.max_spin_rad_s is not None


def test_ackermann_utv_has_no_blade() -> None:
    profile = REFERENCE_PROFILES["ref-ack-utv"]
    assert ROLE_BLADE not in profile.core.actuators
    assert profile.core.blade_inertia_kg_m2 is None
    assert profile.geometry.wheelbase_m is not None
    assert profile.geometry.max_steer_rad is not None


def test_hybrid_mower_declares_four_motor_offsets() -> None:
    profile = REFERENCE_PROFILES["ref-hybrid-mower"]
    offsets = profile.geometry.wheel_lateral_offsets_m
    assert offsets is not None and len(offsets) == 4
    assert all(abs(abs(y) - profile.geometry.track_width_m / 2) < 1e-9 for y in offsets.values())


def _core(**overrides: object) -> ChassisProfile:
    kwargs: dict[str, object] = {
        "model": "test-chassis",
        "kinematics": Kinematics.DIFFERENTIAL,
        "max_linear_speed": 1.0,
        "max_accel": 0.5,
        "max_wheel_speed": 20.0,
        "blade_inertia_kg_m2": None,
        "actuators": {ROLE_LEFT_WHEEL: "a-l", ROLE_RIGHT_WHEEL: "a-r"},
    }
    kwargs.update(overrides)
    return ChassisProfile(**kwargs)  # type: ignore[arg-type]


def _geometry(**overrides: object) -> ChassisGeometry:
    kwargs: dict[str, object] = {"wheel_radius_m": 0.1, "track_width_m": 0.4}
    kwargs.update(overrides)
    return ChassisGeometry(**kwargs)  # type: ignore[arg-type]


def test_validation_rejects_nonpositive_limits() -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        ScalProfile(core=_core(max_linear_speed=-1.0), geometry=_geometry())


def test_validation_rejects_wheel_speed_below_top_speed() -> None:
    with pytest.raises(ValueError, match="below max_linear_speed"):
        ScalProfile(core=_core(max_wheel_speed=5.0), geometry=_geometry())


def test_validation_rejects_missing_wheel_roles() -> None:
    profile = _core(actuators={ROLE_LEFT_WHEEL: "a-l"})
    with pytest.raises(ValueError, match="missing actuator roles"):
        ScalProfile(core=profile, geometry=_geometry())


def test_validation_rejects_missing_spin_bound() -> None:
    with pytest.raises(ValueError, match="max_spin_rad_s is required"):
        ScalProfile(core=_core(), geometry=_geometry(max_spin_rad_s=None))


def test_validation_rejects_spin_beyond_actuator_bound() -> None:
    # Actuator-implied pure-spin bound: 2 * (20 * 0.1) / 0.4 = 10 rad/s.
    with pytest.raises(ValueError, match="exceeds the actuator-implied spin bound"):
        ScalProfile(core=_core(), geometry=_geometry(max_spin_rad_s=10.1))


def test_validation_rejects_ackermann_without_wheelbase() -> None:
    profile = _core(
        kinematics=Kinematics.ACKERMANN,
        max_linear_speed=2.0,
        actuators={
            "rear_left_wheel": "a-rl",
            "rear_right_wheel": "a-rr",
            "steer_left": "a-sl",
            "steer_right": "a-sr",
        },
    )
    with pytest.raises(ValueError, match="wheelbase_m is required"):
        ScalProfile(
            core=profile,
            geometry=_geometry(wheel_radius_m=0.1, track_width_m=0.9, max_steer_rad=0.5),
        )


def test_validation_rejects_ackermann_with_spin_bound() -> None:
    profile = _core(
        kinematics=Kinematics.ACKERMANN,
        max_linear_speed=2.0,
        actuators={
            "rear_left_wheel": "a-rl",
            "rear_right_wheel": "a-rr",
            "steer_left": "a-sl",
            "steer_right": "a-sr",
        },
    )
    with pytest.raises(ValueError, match="does not apply to Ackermann"):
        ScalProfile(
            core=profile,
            geometry=_geometry(
                wheel_radius_m=0.1,
                track_width_m=0.9,
                wheelbase_m=1.2,
                max_steer_rad=0.5,
                max_spin_rad_s=1.0,
            ),
        )


def test_validation_rejects_hybrid_with_wrong_offset_signs() -> None:
    profile = _core(
        kinematics=Kinematics.HYBRID,
        max_linear_speed=1.0,
        actuators={
            "front_left_wheel": "a-fl",
            "front_right_wheel": "a-fr",
            "rear_left_wheel": "a-rl",
            "rear_right_wheel": "a-rr",
        },
    )
    offsets = {
        "front_left_wheel": 0.2,
        "front_right_wheel": 0.2,  # wrong sign
        "rear_left_wheel": 0.2,
        "rear_right_wheel": -0.2,
    }
    with pytest.raises(ValueError, match="needs a negative offset"):
        ScalProfile(
            core=profile, geometry=_geometry(max_spin_rad_s=2.0, wheel_lateral_offsets_m=offsets)
        )


def test_validation_rejects_blade_without_declared_inertia() -> None:
    profile = _core(
        actuators={ROLE_LEFT_WHEEL: "a-l", ROLE_RIGHT_WHEEL: "a-r", ROLE_BLADE: "a-b"}
    )
    with pytest.raises(ValueError, match="must be declared together"):
        ScalProfile(core=profile, geometry=_geometry(max_spin_rad_s=2.0))


def test_wrap_angle_wraps_into_range() -> None:
    assert math.isclose(wrap_angle(math.pi + 0.1), -math.pi + 0.1, abs_tol=1e-12)
    assert math.isclose(wrap_angle(-3.0 * math.pi), -math.pi, abs_tol=1e-12)
    assert wrap_angle(0.0) == 0.0
