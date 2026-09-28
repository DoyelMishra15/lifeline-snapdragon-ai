"""
Tests for lib/qnn_execution.py: execution-mode resolution, provider-list
construction, and session creation guarantees for each of "auto"/"qnn"/
"cpu" — including the hardware-specific pieces (is QNNExecutionProvider
registered, does session creation under it succeed), which are mocked
here so these run on any machine (Codespaces/Linux/x86_64 included),
never requiring real Snapdragon hardware.
"""
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# onnxruntime is an optional dependency (see backend/requirements-snapdragon.txt) —
# skip cleanly rather than fail the suite when it isn't installed, matching
# the rest of the Snapdragon-related test files.
pytest.importorskip("onnxruntime")

from lib import qnn_execution  # noqa: E402


# ---------------------------------------------------------------------------
# resolve_execution_mode
# ---------------------------------------------------------------------------

def test_defaults_to_auto_when_nothing_set(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_MODE, raising=False)
    assert qnn_execution.resolve_execution_mode() == "auto"


def test_explicit_argument_wins_over_env_var(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_MODE, "cpu")
    assert qnn_execution.resolve_execution_mode("qnn") == "qnn"


def test_reads_env_var_when_no_explicit_argument(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_MODE, "qnn")
    assert qnn_execution.resolve_execution_mode() == "qnn"


def test_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_MODE, raising=False)
    assert qnn_execution.resolve_execution_mode("  QNN  ") == "qnn"


def test_invalid_mode_raises_with_clear_reason(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_MODE, raising=False)
    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.resolve_execution_mode("turbo")
    assert exc_info.value.reason == qnn_execution.REASON_INVALID_MODE


def test_invalid_mode_from_env_var_raises(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_MODE, "nonsense")
    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.resolve_execution_mode()
    assert exc_info.value.reason == qnn_execution.REASON_INVALID_MODE
    assert "LIFELINE_OCR_EXECUTION_MODE" in str(exc_info.value)


# ---------------------------------------------------------------------------
# build_providers / qnn_provider_options
# ---------------------------------------------------------------------------

def test_build_providers_cpu_mode_is_cpu_only():
    assert qnn_execution.build_providers("cpu") == [qnn_execution.CPU_PROVIDER]


def test_build_providers_qnn_mode_is_qnn_only_no_cpu_fallback_entry(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_BACKEND_PATH, raising=False)
    providers = qnn_execution.build_providers("qnn")
    assert len(providers) == 1
    name, options = providers[0]
    assert name == qnn_execution.QNN_PROVIDER
    assert "backend_path" in options


def test_build_providers_auto_mode_prefers_qnn_then_cpu(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_BACKEND_PATH, raising=False)
    providers = qnn_execution.build_providers("auto")
    assert len(providers) == 2
    assert providers[0][0] == qnn_execution.QNN_PROVIDER
    assert providers[1] == qnn_execution.CPU_PROVIDER


def test_build_providers_invalid_mode_raises():
    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.build_providers("nope")
    assert exc_info.value.reason == qnn_execution.REASON_INVALID_MODE


def test_qnn_provider_options_default_backend_path_is_platform_appropriate(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_BACKEND_PATH, raising=False)
    monkeypatch.setattr(qnn_execution.platform, "system", lambda: "Windows")
    assert qnn_execution.qnn_provider_options()["backend_path"] == "QnnHtp.dll"

    monkeypatch.setattr(qnn_execution.platform, "system", lambda: "Linux")
    assert qnn_execution.qnn_provider_options()["backend_path"] == "libQnnHtp.so"


def test_qnn_provider_options_backend_path_overridable_via_env(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_BACKEND_PATH, "/custom/path/libQnnHtp.so")
    assert qnn_execution.qnn_provider_options()["backend_path"] == "/custom/path/libQnnHtp.so"


def test_qnn_provider_options_performance_mode_and_htp_arch_only_when_set(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_PERFORMANCE_MODE, raising=False)
    monkeypatch.delenv(qnn_execution.ENV_HTP_ARCH, raising=False)
    options = qnn_execution.qnn_provider_options()
    assert "htp_performance_mode" not in options
    assert "htp_arch" not in options

    monkeypatch.setenv(qnn_execution.ENV_PERFORMANCE_MODE, "burst")
    monkeypatch.setenv(qnn_execution.ENV_HTP_ARCH, "73")
    options = qnn_execution.qnn_provider_options()
    assert options["htp_performance_mode"] == "burst"
    assert options["htp_arch"] == "73"


# ---------------------------------------------------------------------------
# use_mode / get_active_mode
# ---------------------------------------------------------------------------

def test_get_active_mode_is_none_outside_any_scope():
    assert qnn_execution.get_active_mode() is None


def test_use_mode_sets_and_restores_active_mode():
    assert qnn_execution.get_active_mode() is None
    with qnn_execution.use_mode("qnn"):
        assert qnn_execution.get_active_mode() == "qnn"
        with qnn_execution.use_mode("cpu"):
            assert qnn_execution.get_active_mode() == "cpu"
        assert qnn_execution.get_active_mode() == "qnn"
    assert qnn_execution.get_active_mode() is None


def test_use_mode_restores_previous_value_even_on_exception():
    with qnn_execution.use_mode("auto"):
        with pytest.raises(ValueError):
            with qnn_execution.use_mode("qnn"):
                raise ValueError("boom")
        assert qnn_execution.get_active_mode() == "auto"
    assert qnn_execution.get_active_mode() is None


# ---------------------------------------------------------------------------
# create_session — mocked hardware pieces so these run without a
# Snapdragon device: onnxruntime.get_available_providers() and
# onnxruntime.InferenceSession() are monkeypatched to simulate the
# presence/absence of QNNExecutionProvider and successful/failed
# session creation under it.
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, providers):
        self._providers = providers

    def get_providers(self):
        return self._providers


def _fake_inference_session_factory(active_providers):
    """Returns a fake constructor recording calls and returning a session
    whose get_providers() reports `active_providers`."""
    calls = []

    def _factory(model_path, sess_options=None, providers=None):
        calls.append({"model_path": model_path, "providers": providers})
        return _FakeSession(active_providers)

    _factory.calls = calls
    return _factory


def test_create_session_cpu_mode_never_requests_qnn(monkeypatch):
    import onnxruntime

    factory = _fake_inference_session_factory([qnn_execution.CPU_PROVIDER])
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)

    session, active = qnn_execution.create_session("model.onnx", "cpu")
    assert active == qnn_execution.CPU_PROVIDER
    assert factory.calls[0]["providers"] == [qnn_execution.CPU_PROVIDER]


def test_create_session_qnn_mode_raises_when_qnn_not_registered(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: [qnn_execution.CPU_PROVIDER])
    factory = _fake_inference_session_factory([qnn_execution.CPU_PROVIDER])
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)

    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.create_session("model.onnx", "qnn")
    assert exc_info.value.reason == qnn_execution.REASON_QNN_UNAVAILABLE
    # Must fail fast, before ever attempting to build a session.
    assert factory.calls == []


def test_create_session_qnn_mode_succeeds_when_session_reports_qnn_active(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(
        onnxruntime, "get_available_providers",
        lambda: [qnn_execution.QNN_PROVIDER, qnn_execution.CPU_PROVIDER],
    )
    factory = _fake_inference_session_factory([qnn_execution.QNN_PROVIDER])
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)

    session, active = qnn_execution.create_session("model.onnx", "qnn")
    assert active == qnn_execution.QNN_PROVIDER
    # qnn mode must never even include CPU in the requested provider list.
    requested = factory.calls[0]["providers"]
    assert len(requested) == 1
    assert requested[0][0] == qnn_execution.QNN_PROVIDER


def test_create_session_qnn_mode_raises_distinct_reason_when_session_creation_fails(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(
        onnxruntime, "get_available_providers",
        lambda: [qnn_execution.QNN_PROVIDER, qnn_execution.CPU_PROVIDER],
    )

    def _raising_factory(model_path, sess_options=None, providers=None):
        raise RuntimeError("failed to load QNN backend library")

    monkeypatch.setattr(onnxruntime, "InferenceSession", _raising_factory)

    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.create_session("model.onnx", "qnn")
    assert exc_info.value.reason == qnn_execution.REASON_QNN_SESSION_FAILED
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_create_session_qnn_mode_raises_if_session_silently_reports_cpu(monkeypatch):
    # Defensive case: QNN is registered and InferenceSession() doesn't
    # raise, but somehow the active provider isn't QNN. 'qnn' mode must
    # never silently hand back a CPU-backed session.
    import onnxruntime

    monkeypatch.setattr(
        onnxruntime, "get_available_providers",
        lambda: [qnn_execution.QNN_PROVIDER, qnn_execution.CPU_PROVIDER],
    )
    factory = _fake_inference_session_factory([qnn_execution.CPU_PROVIDER])
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)

    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.create_session("model.onnx", "qnn")
    assert exc_info.value.reason == qnn_execution.REASON_QNN_SESSION_FAILED


def test_create_session_auto_mode_uses_cpu_directly_when_qnn_not_registered(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: [qnn_execution.CPU_PROVIDER])
    factory = _fake_inference_session_factory([qnn_execution.CPU_PROVIDER])
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)

    session, active = qnn_execution.create_session("model.onnx", "auto")
    assert active == qnn_execution.CPU_PROVIDER
    # Never even asks onnxruntime for QNN when it isn't registered.
    assert factory.calls[0]["providers"] == [qnn_execution.CPU_PROVIDER]


def test_create_session_auto_mode_prefers_qnn_when_available(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(
        onnxruntime, "get_available_providers",
        lambda: [qnn_execution.QNN_PROVIDER, qnn_execution.CPU_PROVIDER],
    )
    factory = _fake_inference_session_factory([qnn_execution.QNN_PROVIDER])
    monkeypatch.setattr(onnxruntime, "InferenceSession", factory)

    session, active = qnn_execution.create_session("model.onnx", "auto")
    assert active == qnn_execution.QNN_PROVIDER


def test_create_session_auto_mode_falls_back_to_cpu_when_qnn_session_creation_fails(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(
        onnxruntime, "get_available_providers",
        lambda: [qnn_execution.QNN_PROVIDER, qnn_execution.CPU_PROVIDER],
    )

    calls = []

    def _factory(model_path, sess_options=None, providers=None):
        calls.append(providers)
        if providers != [qnn_execution.CPU_PROVIDER]:
            raise RuntimeError("QNN backend not present on this box")
        return _FakeSession([qnn_execution.CPU_PROVIDER])

    monkeypatch.setattr(onnxruntime, "InferenceSession", _factory)

    session, active = qnn_execution.create_session("model.onnx", "auto")
    assert active == qnn_execution.CPU_PROVIDER
    # First attempt included QNN, second (successful) attempt was CPU-only.
    assert len(calls) == 2
    assert calls[1] == [qnn_execution.CPU_PROVIDER]


def test_create_session_invalid_mode_raises():
    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        qnn_execution.create_session("model.onnx", "invalid")
    assert exc_info.value.reason == qnn_execution.REASON_INVALID_MODE


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------

def test_diagnostics_reports_qnn_would_be_used_only_when_registered_and_permitted(monkeypatch):
    import onnxruntime

    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: [qnn_execution.CPU_PROVIDER])
    status = qnn_execution.diagnostics("auto")
    assert status["qnn_provider_registered"] is False
    assert status["qnn_would_be_used"] is False
    assert status["resolved_mode"] == "auto"

    monkeypatch.setattr(
        onnxruntime, "get_available_providers",
        lambda: [qnn_execution.QNN_PROVIDER, qnn_execution.CPU_PROVIDER],
    )
    status = qnn_execution.diagnostics("auto")
    assert status["qnn_provider_registered"] is True
    assert status["qnn_would_be_used"] is True

    status = qnn_execution.diagnostics("cpu")
    assert status["qnn_provider_registered"] is True
    assert status["qnn_would_be_used"] is False


def test_diagnostics_invalid_mode_raises():
    with pytest.raises(qnn_execution.ExecutionModeError):
        qnn_execution.diagnostics("invalid")
