"""
Tests for lib/rapidocr_qnn_session.py — the session wrapper that makes
rapidocr_onnxruntime's ONNX Runtime sessions honor LifeLine's
auto/qnn/cpu execution-mode system (lib/qnn_execution.py), and the
monkeypatch that substitutes it into rapidocr_onnxruntime's three
model-wrapper modules.

Uses one of rapidocr_onnxruntime's own small bundled ONNX models (the
angle-classification model) as a real, valid model file, so these
exercise real onnxruntime session construction — just with the
provider-availability/session-creation pieces mocked where hardware
would otherwise be required, exactly as in test_qnn_execution.py.
"""
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("onnxruntime")
pytest.importorskip("rapidocr_onnxruntime")

from lib import qnn_execution  # noqa: E402
from lib import rapidocr_qnn_session  # noqa: E402


def _real_model_path() -> str:
    import rapidocr_onnxruntime

    root = os.path.dirname(rapidocr_onnxruntime.__file__)
    path = os.path.join(root, "models", "ch_ppocr_mobile_v2.0_cls_infer.onnx")
    assert os.path.isfile(path), "expected rapidocr's bundled cls model to exist"
    return path


def test_raises_file_not_found_for_missing_model_path(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_MODE, raising=False)
    with pytest.raises(FileNotFoundError):
        rapidocr_qnn_session.LifelineOrtInferSession({"model_path": "/no/such/model.onnx"})


def test_raises_value_error_when_model_path_missing_from_config(monkeypatch):
    monkeypatch.delenv(qnn_execution.ENV_MODE, raising=False)
    with pytest.raises(ValueError):
        rapidocr_qnn_session.LifelineOrtInferSession({})


def test_cpu_mode_builds_a_real_working_session(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_MODE, "cpu")
    session = rapidocr_qnn_session.LifelineOrtInferSession({"model_path": _real_model_path()})
    assert session.execution_mode == "cpu"
    assert session.active_provider == qnn_execution.CPU_PROVIDER
    assert session.get_input_names()
    assert session.get_output_names()


def test_call_runs_real_inference_and_returns_session_run_output(monkeypatch):
    import numpy as np

    monkeypatch.setenv(qnn_execution.ENV_MODE, "cpu")
    session = rapidocr_qnn_session.LifelineOrtInferSession({"model_path": _real_model_path()})
    # The cls model's expected input shape is [batch, 3, 48, 192] per
    # rapidocr_onnxruntime/config.yaml's cls_image_shape.
    dummy_input = np.zeros((1, 3, 48, 192), dtype=np.float32)
    outputs = session(dummy_input)
    assert len(outputs) >= 1


def test_qnn_mode_raises_onnx_compatible_error_when_qnn_not_registered(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_MODE, "qnn")
    with pytest.raises(qnn_execution.ExecutionModeError) as exc_info:
        rapidocr_qnn_session.LifelineOrtInferSession({"model_path": _real_model_path()})
    assert exc_info.value.reason == qnn_execution.REASON_QNN_UNAVAILABLE


def test_uses_active_mode_context_over_env_var(monkeypatch):
    # lib/onnx_ocr.py wraps RapidOCR() construction in
    # qnn_execution.use_mode(resolved) so this session class (built deep
    # inside RapidOCR's own constructor) picks up the resolved mode
    # rather than re-reading the environment variable itself.
    monkeypatch.setenv(qnn_execution.ENV_MODE, "qnn")  # would fail if honored directly
    with qnn_execution.use_mode("cpu"):
        session = rapidocr_qnn_session.LifelineOrtInferSession({"model_path": _real_model_path()})
    assert session.execution_mode == "cpu"
    assert session.active_provider == qnn_execution.CPU_PROVIDER


def test_have_key_and_get_character_list_delegate_to_session_metadata(monkeypatch):
    monkeypatch.setenv(qnn_execution.ENV_MODE, "cpu")
    session = rapidocr_qnn_session.LifelineOrtInferSession({"model_path": _real_model_path()})
    # Whatever this model's metadata says, both calls should succeed
    # without raising and agree with each other.
    has_character_key = session.have_key()
    assert isinstance(has_character_key, bool)
    if has_character_key:
        assert isinstance(session.get_character_list(), list)


# ---------------------------------------------------------------------------
# patch_rapidocr_sessions
# ---------------------------------------------------------------------------

def test_patch_rapidocr_sessions_substitutes_all_three_model_wrappers():
    from rapidocr_onnxruntime.ch_ppocr_cls import text_cls
    from rapidocr_onnxruntime.ch_ppocr_det import text_detect
    from rapidocr_onnxruntime.ch_ppocr_rec import text_recognize

    rapidocr_qnn_session.patch_rapidocr_sessions()

    assert text_detect.OrtInferSession is rapidocr_qnn_session.LifelineOrtInferSession
    assert text_cls.OrtInferSession is rapidocr_qnn_session.LifelineOrtInferSession
    assert text_recognize.OrtInferSession is rapidocr_qnn_session.LifelineOrtInferSession
    assert rapidocr_qnn_session.is_patched() is True


def test_patch_rapidocr_sessions_is_idempotent():
    rapidocr_qnn_session.patch_rapidocr_sessions()
    rapidocr_qnn_session.patch_rapidocr_sessions()
    assert rapidocr_qnn_session.is_patched() is True
