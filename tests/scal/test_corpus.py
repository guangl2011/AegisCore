"""Corpus tests: determinism, structure, and the full 100-trajectory property sweep.

The sweep is the acceptance-critical property: no admissible corpus command
may produce actuator values beyond profile limits, on any chassis.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aegiscore.scal.corpus import CORPUS_SEED, CORPUS_SIZE, build_corpus
from aegiscore.scal.profiles import REFERENCE_PROFILES, ScalProfile
from aegiscore.scal.translator import (
    PRIMITIVE_DOCK,
    PRIMITIVE_FOLLOW_PATH,
    PRIMITIVE_MOVE_TO,
    PRIMITIVE_SET_BLADE,
    STEER_ANGLE,
    WHEEL_SPEED,
    Pose2D,
    SCALTranslator,
)

_TASK_VOCABULARY = {
    PRIMITIVE_MOVE_TO,
    PRIMITIVE_FOLLOW_PATH,
    PRIMITIVE_SET_BLADE,
    PRIMITIVE_DOCK,
}


def test_corpus_is_deterministic() -> None:
    assert build_corpus() == build_corpus()


def test_corpus_has_100_unique_trajectories(corpus) -> None:
    assert len(corpus) == CORPUS_SIZE
    assert len({t.trajectory_id for t in corpus}) == CORPUS_SIZE


def test_corpus_seed_is_stable() -> None:
    assert CORPUS_SEED == 20261102


def test_corpus_round_robins_all_three_profiles(corpus) -> None:
    profile_names = list(REFERENCE_PROFILES)
    for index, trajectory in enumerate(corpus):
        assert trajectory.profile_name == profile_names[index % len(profile_names)]


def test_corpus_commands_use_the_task_vocabulary(corpus) -> None:
    for trajectory in corpus:
        assert trajectory.commands
        for cmd in trajectory.commands:
            assert cmd.primitive in _TASK_VOCABULARY, (
                f"corpus emitted unknown primitive {cmd.primitive}"
            )
        issued = [cmd.issued_us for cmd in trajectory.commands]
        assert all(us > 0 for us in issued), "issued_us must be positive"
        assert issued == sorted(issued), "issued_us must increase within a trajectory"


def _assert_within_limits(profile: ScalProfile, value: float, limit: float, what: str) -> None:
    assert abs(value) <= limit, (
        f"{profile.model}: {what} = {value} exceeds limit {limit}"
    )


def test_full_corpus_respects_actuator_limits(corpus) -> None:
    translator = SCALTranslator()
    for trajectory in corpus:
        profile = REFERENCE_PROFILES[trajectory.profile_name]
        steer_max = profile.geometry.max_steer_rad
        blade_max = profile.geometry.blade_max_speed_rad_s
        for cmd in trajectory.commands:
            elements = translator.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
            for element in elements:
                for role, target in element.targets.items():
                    if target.command_type == STEER_ANGLE:
                        assert steer_max is not None
                        _assert_within_limits(profile, target.value, steer_max, "steer angle")
                    elif role in profile.wheel_roles():
                        _assert_within_limits(
                            profile, target.value, profile.core.max_wheel_speed, f"{role} speed"
                        )
                    elif role == profile.blade_role():
                        assert blade_max is not None
                        _assert_within_limits(profile, target.value, blade_max, "blade speed")
                    else:
                        raise AssertionError(f"{profile.model}: unexpected actuator role {role}")


def test_full_corpus_translates_without_error(corpus) -> None:
    """The corpus generator promises in-envelope commands: translation must succeed."""
    translator = SCALTranslator()
    for trajectory in corpus:
        profile = REFERENCE_PROFILES[trajectory.profile_name]
        for cmd in trajectory.commands:
            elements = translator.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
            assert elements is not None
            for element in elements:
                motion_targets = [
                    t for t in element.targets.values() if t.command_type == WHEEL_SPEED
                ]
                if motion_targets:
                    # Motion elements always carry a positive duration.
                    assert element.duration_us > 0
                else:
                    # Blade-only elements are instantaneous configuration writes.
                    assert element.duration_us == 0
                assert element.targets, f"empty targets on {element.source}"


@settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(index=st.integers(min_value=0, max_value=CORPUS_SIZE - 1))
def test_hypothesis_slice_of_corpus_respects_limits(index: int) -> None:
    """Hypothesis-sampled slice of the corpus: same property, shrinking on failure."""
    corpus = build_corpus()
    trajectory = corpus[index]
    profile = REFERENCE_PROFILES[trajectory.profile_name]
    translator = SCALTranslator()
    for cmd in trajectory.commands:
        for element in translator.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0)):
            for role, target in element.targets.items():
                if target.command_type == STEER_ANGLE:
                    steer_max = profile.geometry.max_steer_rad
                    assert steer_max is not None
                    assert abs(target.value) <= steer_max
                elif role in profile.wheel_roles():
                    assert abs(target.value) <= profile.core.max_wheel_speed
                elif role == profile.blade_role():
                    blade_max = profile.geometry.blade_max_speed_rad_s
                    assert blade_max is not None
                    assert abs(target.value) <= blade_max
                else:
                    raise AssertionError(f"{profile.model}: unexpected actuator role {role}")


@settings(deadline=None, max_examples=25)
@given(index=st.integers(min_value=0, max_value=CORPUS_SIZE - 1))
def test_translation_is_pure(index: int) -> None:
    """Re-translating the same command yields an identical stream."""
    corpus = build_corpus()
    trajectory = corpus[index]
    profile = REFERENCE_PROFILES[trajectory.profile_name]
    translator = SCALTranslator()
    for cmd in trajectory.commands:
        first = translator.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
        second = translator.translate(cmd, profile, Pose2D(0.0, 0.0, 0.0))
        assert first == second
