import io
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# The Snapdragon on-device OCR path is an optional dependency (see
# backend/requirements-snapdragon.txt) — skip this whole module rather
# than fail the suite when it isn't installed, matching how the rest
# of the suite already treats Tesseract as an optional system binary.
pytest.importorskip("onnxruntime")
pytest.importorskip("rapidocr_onnxruntime")

from lib import onnx_ocr  # noqa: E402


def _make_test_image_bytes(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 150), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:  # Pillow < 10.1 doesn't support a sized default font
        font = ImageFont.load_default()
    draw.text((20, 50), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extracts_text_from_a_real_generated_image():
    image_bytes = _make_test_image_bytes("Insurance Policy expires 2026-10-14")
    text = onnx_ocr.extract_text_from_image(image_bytes)
    assert "2026-10-14" in text
    assert "Insurance" in text


def test_returns_recognized_text_across_multiple_lines():
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    text = onnx_ocr.extract_text_from_image(image_bytes)
    assert "Warranty" in text
    assert "2026-12-01" in text


def test_raises_onnx_ocr_error_on_corrupt_image_bytes():
    with pytest.raises(onnx_ocr.OnnxOcrError):
        onnx_ocr.extract_text_from_image(b"not an image at all")


def test_available_execution_providers_returns_a_real_nonempty_list():
    # This only reports what onnxruntime actually sees in this process —
    # never asserted to contain QNNExecutionProvider, since that is a
    # Windows-ARM64-only provider that requires real Snapdragon hardware
    # and onnxruntime-qnn to be present (see docs/snapdragon-optimization.md).
    providers = onnx_ocr.available_execution_providers()
    assert isinstance(providers, list)
    assert len(providers) > 0
    assert "CPUExecutionProvider" in providers


# ---------------------------------------------------------------------------
# Execution modes (auto/qnn/cpu) — see lib/qnn_execution.py for the full
# contract. These run on any machine: "cpu" and "auto" are exercised for
# real (this dev environment genuinely has no QNN provider registered),
# and "qnn" is exercised for real too, to confirm it fails loudly here
# rather than needing hardware mocking to prove the negative case.
# ---------------------------------------------------------------------------

def test_explicit_cpu_mode_works_and_reports_cpu_provider(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    text = onnx_ocr.extract_text_from_image(image_bytes, mode="cpu")
    assert "2026-12-01" in text

    status = onnx_ocr.runtime_status(mode="cpu")
    assert status["resolved_mode"] == "cpu"
    assert status["engine_active_provider"] == "CPUExecutionProvider"


def test_auto_mode_falls_back_to_cpu_when_no_qnn_hardware_present(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    text = onnx_ocr.extract_text_from_image(image_bytes, mode="auto")
    assert "2026-12-01" in text

    status = onnx_ocr.runtime_status(mode="auto")
    assert status["resolved_mode"] == "auto"
    # This dev/CI environment has no QNN backend installed, so auto mode
    # must have transparently used CPU rather than raising.
    assert status["engine_active_provider"] == "CPUExecutionProvider"


def test_explicit_qnn_mode_fails_clearly_instead_of_silently_using_cpu(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    with pytest.raises(onnx_ocr.OnnxOcrError) as exc_info:
        onnx_ocr.extract_text_from_image(image_bytes, mode="qnn")
    # Distinguishable failure reason (see lib/qnn_execution.py) rather
    # than a generic error or, worse, a silent CPU fallback.
    assert exc_info.value.reason == "qnn_unavailable"


def test_execution_mode_env_var_is_honored_when_no_explicit_mode_given(monkeypatch):
    monkeypatch.setenv("LIFELINE_OCR_EXECUTION_MODE", "cpu")
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    text = onnx_ocr.extract_text_from_image(image_bytes)
    assert "2026-12-01" in text
    status = onnx_ocr.runtime_status()
    assert status["resolved_mode"] == "cpu"


def test_invalid_execution_mode_raises_onnx_ocr_error(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    with pytest.raises(onnx_ocr.OnnxOcrError) as exc_info:
        onnx_ocr.extract_text_from_image(b"irrelevant", mode="not-a-real-mode")
    assert exc_info.value.reason == "invalid_mode"


def test_runtime_status_reports_expected_shape(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    status = onnx_ocr.runtime_status()
    for key in (
        "requested_mode", "resolved_mode", "available_providers",
        "qnn_provider_registered", "qnn_would_be_used", "qnn_backend_path",
        "platform", "machine", "engine_loaded", "engine_mode",
        "engine_active_provider",
    ):
        assert key in status
