"""AdvisoryConstraint validation: the spec's interface contract, enforced."""

from __future__ import annotations

import dataclasses
from math import inf, nan
from typing import get_type_hints

import pytest

import aegiscore.advisory as advisory_pkg
from aegiscore.advisory import (
    AdvisoryConstraint,
    AdvisoryKind,
    pinned_model_ref,
    validate_source_model,
)

FULL_SHA = "a" * 40
REF = f"OpenVINO/advisory@{FULL_SHA}"


def make(**overrides: object) -> AdvisoryConstraint:
    fields: dict[str, object] = {
        "kind": AdvisoryKind.ANOMALY_FLAG,
        "severity": 0.5,
        "source_model": REF,
        "issued_monotonic_ns": 42,
    }
    fields.update(overrides)
    return AdvisoryConstraint(**fields)


class TestKind:
    def test_enum_member_accepted(self) -> None:
        assert make(kind=AdvisoryKind.TERRAIN_RISK).kind is AdvisoryKind.TERRAIN_RISK

    def test_spec_literal_string_coerced(self) -> None:
        assert make(kind="proximity_margin").kind is AdvisoryKind.PROXIMITY_MARGIN

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="kind must be one of"):
            make(kind="smell")


class TestSeverity:
    @pytest.mark.parametrize("value", [-0.01, 1.01, nan, inf, -inf])
    def test_out_of_range_or_non_finite_rejected(self, value: float) -> None:
        with pytest.raises(ValueError, match="severity"):
            make(severity=value)

    @pytest.mark.parametrize("value", [True, False, "0.5", None])
    def test_wrong_type_rejected(self, value: object) -> None:
        with pytest.raises(TypeError, match="severity"):
            make(severity=value)

    def test_int_coerced_to_float(self) -> None:
        constraint = make(severity=1)
        assert constraint.severity == 1.0
        assert isinstance(constraint.severity, float)


class TestIssuedMonotonicNs:
    @pytest.mark.parametrize("value", [True, 1.5, "42", None])
    def test_wrong_type_rejected(self, value: object) -> None:
        with pytest.raises(TypeError, match="issued_monotonic_ns"):
            make(issued_monotonic_ns=value)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            make(issued_monotonic_ns=-1)


class TestSourceModelPinning:
    @pytest.mark.parametrize(
        "ref",
        [
            "OpenVINO/advisory",  # no @revision at all
            "OpenVINO/advisory@main",  # tag, not a reviewed SHA
            f"OpenVINO/advisory@{FULL_SHA[:-1]}g",  # revision is not hex
            "OpenVINO/advisory@abc123",  # shorter than 7 hex chars
            f"OpenVINO/advisory@{'g' * 40}",  # non-hex full-length
            "",  # empty
        ],
    )
    def test_unpinned_references_rejected(self, ref: str) -> None:
        with pytest.raises(ValueError, match="source_model"):
            make(source_model=ref)

    def test_short_sha_prefix_accepted(self) -> None:
        assert validate_source_model(f"m@{FULL_SHA[:7]}") == f"m@{FULL_SHA[:7]}"

    def test_pinned_model_ref_formats_and_validates(self) -> None:
        ref = pinned_model_ref("OpenVINO/advisory", FULL_SHA)
        assert ref == REF
        with pytest.raises(ValueError, match="source_model"):
            pinned_model_ref("OpenVINO/advisory", "main")


class TestInterfaceContract:
    """Structural guarantees the governor and reviewers rely on."""

    def test_fields_are_exactly_the_spec_contract(self) -> None:
        assert {f.name for f in dataclasses.fields(AdvisoryConstraint)} == {
            "kind",
            "severity",
            "source_model",
            "issued_monotonic_ns",
        }

    def test_frozen(self) -> None:
        constraint = make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            constraint.severity = 0.9  # type: ignore[misc]

    def test_equality_and_hash(self) -> None:
        assert make() == make()
        assert hash(make()) == hash(make())

    def test_public_api_has_no_command_or_actuator_surface(self) -> None:
        # The advisory layer's entire public vocabulary must be command-free:
        # no inference output may write or modify an actuator command.
        assert advisory_pkg.__all__, "public API must be declared"
        for name in advisory_pkg.__all__:
            lowered = name.lower()
            assert "command" not in lowered and "actuator" not in lowered, name

    def test_constraint_annotations_mention_no_actuator_command(self) -> None:
        hints = get_type_hints(AdvisoryConstraint)
        assert not any("ActuatorCommand" in str(hint) for hint in hints.values())
