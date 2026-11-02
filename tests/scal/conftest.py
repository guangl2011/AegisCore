"""Shared fixtures for SCAL tests."""

import pytest

from aegiscore.scal.corpus import Trajectory, build_corpus
from aegiscore.scal.profiles import REFERENCE_PROFILES, ScalProfile


@pytest.fixture(scope="session")
def corpus() -> list[Trajectory]:
    return build_corpus()


@pytest.fixture(scope="session")
def diff_profile() -> ScalProfile:
    return REFERENCE_PROFILES["ref-diff-mower"]


@pytest.fixture(scope="session")
def ackermann_profile() -> ScalProfile:
    return REFERENCE_PROFILES["ref-ack-utv"]


@pytest.fixture(scope="session")
def hybrid_profile() -> ScalProfile:
    return REFERENCE_PROFILES["ref-hybrid-mower"]


def all_reference_profiles() -> list[ScalProfile]:
    return list(REFERENCE_PROFILES.values())
