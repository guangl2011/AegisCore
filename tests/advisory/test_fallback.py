"""Fallback chain and silent CPU degrade — the factories and select_provider.

Backends are simulated by injecting fake modules into ``sys.modules`` (the
real import machinery does the rest), so these tests run on hosts with no
physicalai, openvino, or onnxruntime — including CI.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
from stubs import MODEL_REF, StubFrame

from aegiscore.advisory import (
    NullAdvisoryProvider,
    OnnxRuntimeAdvisoryProvider,
    OpenVINOAdvisoryProvider,
    create_onnx_provider,
    create_openvino_provider,
    select_provider,
)

EXPORT_DIR = "/exports/advisory-model"
ONNX_PATH = "/models/advisory.onnx"


def make_fake_physicalai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_devices: tuple[str, ...] = (),
    devices_requested: list[str] | None = None,
) -> None:
    """Install a fake ``physicalai.inference`` module with the documented
    ``InferenceModel`` constructor signature."""

    class FakeInferenceModel:
        def __init__(
            self,
            export_dir: Any,
            policy_name: str | None = None,
            backend: str = "auto",
            device: str = "auto",
        ) -> None:
            if devices_requested is not None:
                devices_requested.append(device)
            if device in fail_devices:
                msg = f"device {device} unavailable"
                raise RuntimeError(msg)
            self.device = device

        def select_action(self, observation: Any) -> Any:
            return 0.4

        def close(self) -> None:
            return None

    module = ModuleType("physicalai.inference")
    module.InferenceModel = FakeInferenceModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "physicalai.inference", module)


def make_fake_ort(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_providers: tuple[str, ...] = (),
    actual_providers: list[str] | None = None,
) -> list[Any]:
    """Install a fake ``onnxruntime`` module; return the sessions created."""

    class FakeSession:
        def __init__(self, model_path: str, providers: list[str] | None = None) -> None:
            created.append(self)
            self.model_path = model_path
            self.requested = providers
            self.feeds: list[dict[str, Any]] = []
            self.closed = False
            if providers and any(p in fail_providers for p in providers):
                msg = f"requested providers unavailable: {providers}"
                raise RuntimeError(msg)

        def get_providers(self) -> list[str]:
            if actual_providers is not None:
                return actual_providers
            return list(self.requested or ["CPUExecutionProvider"])

        def get_inputs(self) -> list[Any]:
            class _Input:
                name = "frame"

            return [_Input()]

        def run(self, output_names: Any, input_feed: dict[str, Any]) -> list[Any]:
            self.feeds.append(input_feed)
            return [0.6]

        def close(self) -> None:
            self.closed = True

    created: list[Any] = []
    module = ModuleType("onnxruntime")
    module.InferenceSession = FakeSession  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    return created


class TestOpenVINODeviceDegrade:
    def test_missing_npu_degrades_silently_to_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        requested: list[str] = []
        make_fake_physicalai(monkeypatch, fail_devices=("NPU",), devices_requested=requested)
        provider = create_openvino_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            device="NPU",
        )
        # Silent: no exception, provider simply reports the degraded device.
        assert provider.device == "CPU"
        assert provider.degraded is True
        (constraint,) = provider.poll()
        assert constraint.severity == 0.4
        assert requested == ["NPU", "CPU"]  # tried NPU first, retried on CPU

    def test_available_npu_runs_without_degrade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        requested: list[str] = []
        make_fake_physicalai(monkeypatch, devices_requested=requested)
        provider = create_openvino_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            device="NPU",
        )
        assert provider.device == "NPU"
        assert provider.degraded is False
        assert requested == ["NPU"]

    def test_requested_cpu_never_degrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        make_fake_physicalai(monkeypatch)
        provider = create_openvino_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            device="CPU",
        )
        assert provider.device == "CPU"
        assert provider.degraded is False

    def test_physicalai_absent_raises_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Absence of the optional runtime is the fallback trigger, not a
        # degrade: create_openvino_provider propagates, select_provider handles.
        monkeypatch.setitem(sys.modules, "physicalai.inference", None)
        with pytest.raises(ImportError):
            create_openvino_provider(
                export_dir=EXPORT_DIR,
                kind="anomaly_flag",
                model_ref=MODEL_REF,
                read_frame=lambda: StubFrame(data="f"),
            )

    def test_cpu_fallback_failure_is_a_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A model that fails to compile even on CPU is not a degrade condition.
        make_fake_physicalai(monkeypatch, fail_devices=("NPU", "CPU"))
        with pytest.raises(RuntimeError):
            create_openvino_provider(
                export_dir=EXPORT_DIR,
                kind="anomaly_flag",
                model_ref=MODEL_REF,
                read_frame=lambda: StubFrame(data="f"),
                device="NPU",
            )

    def test_input_source_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        make_fake_physicalai(monkeypatch)
        with pytest.raises(ValueError, match="input source"):
            create_openvino_provider(
                export_dir=EXPORT_DIR,
                kind="anomaly_flag",
                model_ref=MODEL_REF,
            )

    def test_full_poll_round_trip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        make_fake_physicalai(monkeypatch)
        provider = create_openvino_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="frame-bytes"),
            device="GPU",
            clock=lambda: 7,
        )
        (constraint,) = provider.poll()
        assert constraint.severity == 0.4  # the fake model's canned score
        assert constraint.issued_monotonic_ns == 7
        assert constraint.source_model == MODEL_REF


class TestOnnxProvider:
    def test_happy_path_with_auto_input_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created = make_fake_ort(monkeypatch)
        provider = create_onnx_provider(
            model_path=ONNX_PATH,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="frame-bytes"),
        )
        (constraint,) = provider.poll()
        assert constraint.severity == 0.6
        assert provider.device == "CPUExecutionProvider"
        assert provider.degraded is False
        assert created[0].feeds == [{"frame": "frame-bytes"}]

    def test_unavailable_execution_provider_recorded_as_degraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # onnxruntime substitutes CPU for an unavailable provider without
        # raising — the session's provider list is the only evidence.
        make_fake_ort(monkeypatch, actual_providers=["CPUExecutionProvider"])
        provider = create_onnx_provider(
            model_path=ONNX_PATH,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        assert provider.degraded is True
        assert provider.device == "CPUExecutionProvider"

    def test_runtime_error_retries_on_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created = make_fake_ort(monkeypatch, fail_providers=("CUDAExecutionProvider",))
        provider = create_onnx_provider(
            model_path=ONNX_PATH,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            providers=["CUDAExecutionProvider"],
        )
        assert provider.degraded is True
        assert created[-1].requested == ["CPUExecutionProvider"]  # retry session

    def test_close_releases_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created = make_fake_ort(monkeypatch)
        provider = create_onnx_provider(
            model_path=ONNX_PATH,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
        )
        provider.close()
        assert created[0].closed is True

    def test_onnxruntime_absent_raises_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "onnxruntime", None)
        with pytest.raises(ImportError):
            create_onnx_provider(
                model_path=ONNX_PATH,
                kind="anomaly_flag",
                model_ref=MODEL_REF,
                read_frame=lambda: StubFrame(data="f"),
            )


class TestSelectProviderChain:
    def test_prefers_openvino_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        make_fake_physicalai(monkeypatch)
        make_fake_ort(monkeypatch)
        provider = select_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
        )
        assert isinstance(provider, OpenVINOAdvisoryProvider)

    def test_falls_back_to_onnx_when_physicalai_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "physicalai.inference", None)
        make_fake_ort(monkeypatch)
        provider = select_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            onnx_model_path=ONNX_PATH,
        )
        assert isinstance(provider, OnnxRuntimeAdvisoryProvider)
        assert provider.degraded is False

    def test_falls_back_to_null_when_no_onnx_model_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "physicalai.inference", None)
        provider = select_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
        )
        assert isinstance(provider, NullAdvisoryProvider)

    def test_falls_back_to_null_when_onnxruntime_also_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "physicalai.inference", None)
        monkeypatch.setitem(sys.modules, "onnxruntime", None)
        provider = select_provider(
            export_dir=EXPORT_DIR,
            kind="anomaly_flag",
            model_ref=MODEL_REF,
            read_frame=lambda: StubFrame(data="f"),
            onnx_model_path=ONNX_PATH,
        )
        assert isinstance(provider, NullAdvisoryProvider)
