"""Shared scoring machinery: poll pipeline, error isolation, protocol shape."""

from __future__ import annotations

from math import nan

import pytest
from stubs import MODEL_REF, FakeArray, StubCamera, StubFrame, StubModel

from aegiscore.advisory import (
    AdvisoryConstraint,
    AdvisoryKind,
    AdvisoryProvider,
    NullAdvisoryProvider,
    OpenVINOAdvisoryProvider,
    scalar_score,
    severity_from_score,
)

FIXED_NS = 1_000_000


def make_provider(
    *, model: StubModel | None = None, **overrides: object
) -> OpenVINOAdvisoryProvider:
    base: dict[str, object] = {
        "model": model if model is not None else StubModel(score=0.7),
        "kind": "anomaly_flag",
        "model_ref": MODEL_REF,
        "read_frame": lambda: StubFrame(data="frame-data"),
        "device": "NPU",
        "clock": lambda: FIXED_NS,
    }
    base.update(overrides)
    return OpenVINOAdvisoryProvider(**base)


class TestProtocolConformance:
    def test_openvino_provider_satisfies_protocol(self) -> None:
        assert isinstance(make_provider(), AdvisoryProvider)

    def test_null_provider_satisfies_protocol(self) -> None:
        assert isinstance(NullAdvisoryProvider(), AdvisoryProvider)

    def test_provider_stays_poll_only(self) -> None:
        # The protocol's member set is the safety contract: poll for
        # constraints, close for teardown. Nothing command-shaped. (dir-filter
        # works on both 3.11 and 3.12, unlike __protocol_attrs__.)
        members = {
            name
            for name in dir(AdvisoryProvider)
            if not name.startswith("_")
        }
        assert members == {"device", "degraded", "poll", "close"}


class TestPollPipeline:
    def test_emits_one_constraint_with_spec_fields(self) -> None:
        provider = make_provider()
        (constraint,) = provider.poll()
        assert isinstance(constraint, AdvisoryConstraint)
        assert constraint.kind is AdvisoryKind.ANOMALY_FLAG
        assert constraint.severity == 0.7
        assert constraint.source_model == MODEL_REF
        assert constraint.issued_monotonic_ns == FIXED_NS

    def test_frame_data_flows_to_model(self) -> None:
        model = StubModel(score=0.7)
        provider = make_provider(model=model)
        provider.poll()
        assert model.observations == ["frame-data"]

    def test_obs_fn_shapes_the_observation(self) -> None:
        model = StubModel(score=0.7)
        provider = make_provider(model=model, obs_fn=lambda data: {"frames": data})
        provider.poll()
        assert model.observations == [{"frames": "frame-data"}]

    def test_score_fn_scales_the_raw_output(self) -> None:
        provider = make_provider(model=StubModel(score=0.3), score_fn=lambda raw: raw * 2)
        (constraint,) = provider.poll()
        assert constraint.severity == 0.6

    def test_missing_frame_yields_no_constraint(self) -> None:
        provider = make_provider(read_frame=lambda: None)
        assert provider.poll() == ()
        assert provider.error_count == 0

    @pytest.mark.parametrize(
        ("raw", "expected"), [(1.5, 1.0), (-3.0, 0.0), (0.42, 0.42)]
    )
    def test_severity_clamped_to_unit_range(self, raw: float, expected: float) -> None:
        provider = make_provider(model=StubModel(score=raw))
        (constraint,) = provider.poll()
        assert constraint.severity == expected

    def test_min_severity_drops_weak_signals(self) -> None:
        provider = make_provider(
            model=StubModel(score=0.4),
            read_frame=lambda: StubFrame(data="x"),
            min_severity=0.5,
        )
        assert provider.poll() == ()
        assert provider.error_count == 0

    def test_min_severity_validated_at_construction(self) -> None:
        with pytest.raises(ValueError, match="min_severity"):
            make_provider(min_severity=1.5)

    def test_kind_and_model_ref_validated_at_construction(self) -> None:
        with pytest.raises(ValueError, match="kind must be one of"):
            make_provider(kind="smell")
        with pytest.raises(ValueError, match="source_model"):
            make_provider(model_ref="unpinned-model")


class TestErrorIsolation:
    """Advisory failures are recorded, never propagated into the loop."""

    def test_model_fault_recorded_and_dropped(self) -> None:
        model = StubModel(error=RuntimeError("NPU driver crashed"))
        provider = make_provider(model=model)
        assert provider.poll() == ()
        assert provider.error_count == 1
        assert provider.last_error is not None
        assert "RuntimeError" in provider.last_error and "NPU driver" in provider.last_error

    def test_recovers_after_a_fault(self) -> None:
        model = StubModel(score=0.5, error=RuntimeError("transient"))
        provider = make_provider(model=model)
        assert provider.poll() == ()
        model.error = None
        (constraint,) = provider.poll()
        assert constraint.severity == 0.5
        assert provider.error_count == 1  # cumulative, not reset on success

    def test_read_frame_fault_isolated(self) -> None:
        def broken_reader() -> StubFrame:
            raise OSError("camera unplugged")

        provider = make_provider(read_frame=broken_reader)
        assert provider.poll() == ()
        assert "OSError" in (provider.last_error or "")

    def test_malformed_model_output_isolated(self) -> None:
        provider = make_provider(model=StubModel(score={"a": 1.0, "b": 2.0}))
        assert provider.poll() == ()
        assert "exactly one model output" in (provider.last_error or "")


class TestLifecycle:
    def test_close_releases_the_model(self) -> None:
        model = StubModel(score=0.7)
        provider = make_provider(model=model)
        provider.close()
        assert model.closed is True


class TestNullProvider:
    def test_publishes_nothing_and_degrades_nothing(self) -> None:
        provider = NullAdvisoryProvider()
        assert provider.device == "none"
        assert provider.degraded is False
        assert provider.poll() == ()
        provider.close()  # no-op, must not raise


class TestScalarScore:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.5, 0.5),
            (2, 2.0),
            ({"risk": 0.7}, 0.7),
            ([0.3], 0.3),
            ((0.9,), 0.9),
            (FakeArray(0.1), 0.1),
        ],
    )
    def test_accepts_single_value_shapes(self, value: object, expected: float) -> None:
        assert scalar_score(value) == expected

    @pytest.mark.parametrize(
        "value",
        [{"a": 1.0, "b": 2.0}, [1.0, 2.0], FakeArray(0.5, size=3), "abc", None],
    )
    def test_rejects_ambiguous_or_useless_shapes(self, value: object) -> None:
        with pytest.raises(ValueError, match="output|score"):
            scalar_score(value)

    def test_non_finite_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            scalar_score(nan)


class TestSeverityFromScore:
    def test_non_finite_means_no_signal(self) -> None:
        assert severity_from_score(nan) is None
        assert severity_from_score(float("inf")) is None

    def test_clamps_into_unit_range(self) -> None:
        assert severity_from_score(2.0) == 1.0
        assert severity_from_score(-1.0) == 0.0

    def test_min_severity_threshold(self) -> None:
        assert severity_from_score(0.4, min_severity=0.5) is None
        assert severity_from_score(0.6, min_severity=0.5) == 0.6


class TestCameraWiring:
    def test_camera_read_latest_is_the_default_frame_source(self) -> None:
        camera = StubCamera(StubFrame(data="camera-frame"))
        model = StubModel(score=0.8)
        provider = make_provider(model=model, read_frame=camera.read_latest)
        (constraint,) = provider.poll()
        assert constraint.severity == 0.8
        assert model.observations == ["camera-frame"]
