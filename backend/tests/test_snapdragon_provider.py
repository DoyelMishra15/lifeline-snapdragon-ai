import io
import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("onnxruntime")
pytest.importorskip("rapidocr_onnxruntime")

from lib import snapdragon_provider  # noqa: E402


def _make_test_image_bytes(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 150), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((20, 50), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_document_from_text_reuses_local_reasoning_unchanged():
    result = snapdragon_provider.extract_document(
        text="Health Insurance Policy\nProvider: Acme Insurance\nThis policy expires on 2026-10-14."
    )
    assert result["ok"] is True
    doc = json.loads(result["text"])
    assert doc["document_type"] == "insurance"
    assert doc["expiry_date"] == "2026-10-14"
    assert doc["provider"] == "Acme Insurance"


def test_extract_document_from_image_runs_on_device_ocr_then_structures_it():
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    result = snapdragon_provider.extract_document(image_bytes=image_bytes)
    assert result["ok"] is True
    doc = json.loads(result["text"])
    assert doc["document_type"] == "warranty"
    assert doc["expiry_date"] == "2026-12-01"


def test_extract_document_from_image_returns_failure_on_corrupt_bytes():
    result = snapdragon_provider.extract_document(image_bytes=b"not an image at all")
    assert result["ok"] is False
    assert result["retryable"] is False


def test_draft_emergency_plan_delegates_to_local_reasoning_unchanged():
    result = snapdragon_provider.draft_emergency_plan(situation="Other", user_data={"documents": []})
    assert result["ok"] is True
    plan = json.loads(result["text"])
    assert "disclaimer" in plan


def test_runtime_status_reports_execution_mode_and_active_provider(monkeypatch):
    monkeypatch.setenv("LIFELINE_OCR_EXECUTION_MODE", "cpu")
    # Trigger engine construction so engine_active_provider is populated.
    image_bytes = _make_test_image_bytes("Warranty Card valid until 2026-12-01")
    snapdragon_provider.extract_document(image_bytes=image_bytes)

    status = snapdragon_provider.runtime_status()
    assert status["resolved_mode"] == "cpu"
    assert status["engine_active_provider"] == "CPUExecutionProvider"
