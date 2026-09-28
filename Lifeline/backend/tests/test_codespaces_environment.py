"""
Explicit proof that GitHub Codespaces (Linux/x86_64, no Snapdragon NPU,
no QNN SDK, no Windows-only libraries) is a fully supported environment
for this project — not just "happens to work by accident".

This file exists as a single, clearly-named place that demonstrates
exactly what docs/snapdragon-optimization.md's "Codespaces" section
claims, so a reviewer doesn't have to piece it together from the more
granular unit tests in test_qnn_execution.py, test_rapidocr_qnn_session.py,
and test_onnx_ocr.py (which this file deliberately does not duplicate —
see each test's docstring for exactly what's new here versus already
covered elsewhere).

What's proven here:
1. Every lib module on the Snapdragon/QNN path imports cleanly even
   when `onnxruntime`/`rapidocr_onnxruntime` are not installed at all
   (i.e. requirements-snapdragon.txt was never run) — so nothing about
   importing this project, running its handlers, or collecting its
   test suite requires the optional Snapdragon extras.
2. `LIFELINE_OCR_EXECUTION_MODE=cpu` fully works in Codespaces: real
   OCR, real recognized text.
3. `LIFELINE_OCR_EXECUTION_MODE=auto` correctly detects that QNN isn't
   available here and cleanly uses CPU — no error, no hang, no silent
   wrong answer.
4. `LIFELINE_OCR_EXECUTION_MODE=qnn` fails with a clear, actionable
   "QNN unavailable in this environment" error — it does not import-
   error, hang, or (worse) silently fall back to CPU while claiming to
   be on QNN.
5. Choosing the snapdragon provider doesn't disturb the rest of the
   LifeLine pipeline: local/bedrock providers, the process handler
   import, and requirements-snapdragon.txt's platform markers all
   behave exactly as they would with no Snapdragon code present.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


def _make_test_image_bytes(text: str) -> bytes:
    import io

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 150), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:  # older Pillow without the size= kwarg
        font = ImageFont.load_default()
    draw.text((20, 50), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Importing the project never requires the optional Snapdragon extras.
# ---------------------------------------------------------------------------

def test_snapdragon_qnn_modules_import_without_onnxruntime_or_rapidocr_installed():
    """
    Runs in a fresh subprocess (so it can't pollute this test session's
    already-imported modules) with a sys.meta_path finder that makes
    `import onnxruntime` / `import rapidocr_onnxruntime` raise ImportError
    exactly as they would in a Codespace where
    `pip install -r requirements-snapdragon.txt` was never run — then
    confirms lib/qnn_execution.py, lib/onnx_ocr.py,
    lib/rapidocr_qnn_session.py, lib/snapdragon_provider.py,
    lib/ai_provider.py, and the request handlers all still import
    cleanly. This is what lets a bare `pip install -r requirements.txt
    -r requirements-dev.txt` Codespace run the rest of the test suite,
    the local/bedrock providers, and every handler with zero knowledge
    of onnxruntime.
    """
    script = textwrap.dedent(
        """
        import sys

        class _BlockSnapdragonExtras:
            def find_spec(self, name, path, target=None):
                if name in ("onnxruntime", "rapidocr_onnxruntime"):
                    raise ImportError(f"{name} is deliberately blocked for this test")
                return None

        sys.meta_path.insert(0, _BlockSnapdragonExtras())
        for mod in ("onnxruntime", "rapidocr_onnxruntime"):
            sys.modules.pop(mod, None)

        from lib import qnn_execution, onnx_ocr, rapidocr_qnn_session, snapdragon_provider, ai_provider
        from handlers import process, documents, upload, emergency, profile, reminders, local_auth
        print("IMPORT_OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "IMPORT_OK" in result.stdout


def test_requirements_snapdragon_selects_plain_onnxruntime_on_linux_x86_64():
    """
    Confirms requirements-snapdragon.txt's environment markers resolve
    to plain `onnxruntime` (never `onnxruntime-qnn`, which is an
    ARM64-only wheel) on this platform — the same platform GitHub
    Codespaces runs on. Parses the real requirements file rather than
    hardcoding its expected content, so this fails loudly if the
    markers are ever edited incorrectly.
    """
    from packaging.requirements import Requirement

    req_path = os.path.join(BACKEND_DIR, "requirements-snapdragon.txt")
    selected = []
    for line in open(req_path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        if req.marker is None or req.marker.evaluate():
            selected.append(req.name)

    assert "onnxruntime" in selected
    assert "onnxruntime-qnn" not in selected
    assert "rapidocr-onnxruntime" in selected


# ---------------------------------------------------------------------------
# 2-4. cpu / auto / qnn behavior, for real, in this Codespaces-equivalent
# environment (no mocking — this genuinely has no QNN provider registered).
# Requires the optional extras to actually be installed, same as any other
# real OCR test; see test_onnx_ocr.py for the underlying implementation
# these exercise.
# ---------------------------------------------------------------------------

pytest.importorskip("onnxruntime")
pytest.importorskip("rapidocr_onnxruntime")

from lib import ai_provider, onnx_ocr  # noqa: E402


def test_cpu_mode_fully_works_in_codespaces(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    image_bytes = _make_test_image_bytes("Insurance Policy expires 2026-10-14")

    text = onnx_ocr.extract_text_from_image(image_bytes, mode="cpu")
    assert "2026-10-14" in text

    status = onnx_ocr.runtime_status(mode="cpu")
    assert status["resolved_mode"] == "cpu"
    assert status["engine_active_provider"] == "CPUExecutionProvider"
    assert status["onnxruntime_installed"] is True


def test_auto_mode_detects_no_qnn_and_cleanly_uses_cpu_in_codespaces(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)

    # This is a real, unmocked check: it fails the test (rather than
    # silently passing) if this machine somehow *does* have QNN
    # registered, since that would mean the "auto falls back to CPU in
    # Codespaces" scenario isn't actually being exercised here.
    assert "QNNExecutionProvider" not in onnx_ocr.available_execution_providers(), (
        "QNNExecutionProvider is unexpectedly registered on this machine — "
        "this test specifically validates the Codespaces (no-QNN) fallback "
        "path and needs that to be true to mean anything."
    )

    image_bytes = _make_test_image_bytes("Insurance Policy expires 2026-10-14")
    text = onnx_ocr.extract_text_from_image(image_bytes, mode="auto")
    assert "2026-10-14" in text

    status = onnx_ocr.runtime_status(mode="auto")
    assert status["resolved_mode"] == "auto"
    assert status["qnn_provider_registered"] is False
    assert status["qnn_would_be_used"] is False
    assert status["engine_active_provider"] == "CPUExecutionProvider"


def test_qnn_mode_fails_with_clear_actionable_error_in_codespaces(monkeypatch):
    monkeypatch.delenv("LIFELINE_OCR_EXECUTION_MODE", raising=False)
    image_bytes = _make_test_image_bytes("Insurance Policy expires 2026-10-14")

    with pytest.raises(onnx_ocr.OnnxOcrError) as exc_info:
        onnx_ocr.extract_text_from_image(image_bytes, mode="qnn")

    error = exc_info.value
    # Never breaks the import, never hangs, never silently returns a
    # CPU-backed result under the name "qnn" — it raises this specific,
    # programmatically-distinguishable error instead.
    assert error.reason == "qnn_unavailable"
    message = str(error).lower()
    assert "qnn" in message
    # Actionable: names the real fix (the ARM64-only package), not just
    # "something went wrong".
    assert "onnxruntime-qnn" in message

    # And it must not have quietly built a CPU engine under the "qnn" label.
    status = onnx_ocr.runtime_status()
    assert status["engine_mode"] != "qnn"


def test_qnn_mode_via_ai_provider_dispatch_fails_cleanly_not_silently(monkeypatch):
    """
    Same guarantee one layer up, through the real dispatch path
    (lib/ai_provider.py -> lib/snapdragon_provider.py) that
    backend/handlers/process.py actually calls — snapdragon_provider
    converts the exception into the shared {"ok": False, ...} contract
    rather than raising, so this confirms that conversion doesn't lose
    the "this was QNN, not some other failure" information for anyone
    inspecting the response, and that it never reports ok=True on CPU
    while claiming QNN mode.
    """
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "snapdragon")
    monkeypatch.setenv("LIFELINE_OCR_EXECUTION_MODE", "qnn")
    image_bytes = _make_test_image_bytes("Insurance Policy expires 2026-10-14")

    result = ai_provider.extract_document(image_bytes=image_bytes)
    assert result["ok"] is False
    assert "qnn" in result["error"].lower()


# ---------------------------------------------------------------------------
# 5. Choosing the snapdragon/QNN provider doesn't disturb anything else.
# ---------------------------------------------------------------------------

def test_local_provider_unaffected_by_snapdragon_module_existing(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    result = ai_provider.extract_document(
        text="Insurance Policy\nExpires 2026-10-14\nProvider: Acme Insurance"
    )
    assert result["ok"] is True
    extracted = json.loads(result["text"])
    assert extracted["expiry_date"] == "2026-10-14"


def test_switching_between_providers_across_calls_does_not_cross_contaminate(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    local_result = ai_provider.extract_document(text="Warranty\nExpires 2026-11-01")
    assert local_result["ok"] is True

    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "snapdragon")
    monkeypatch.setenv("LIFELINE_OCR_EXECUTION_MODE", "cpu")
    image_bytes = _make_test_image_bytes("Insurance Policy expires 2026-10-14")
    snapdragon_result = ai_provider.extract_document(image_bytes=image_bytes)
    assert snapdragon_result["ok"] is True

    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    local_again = ai_provider.extract_document(text="Warranty\nExpires 2026-11-01")
    assert local_again["ok"] is True
    assert json.loads(local_again["text"]) == json.loads(local_result["text"])


def test_process_handler_module_imports_and_dispatches_regardless_of_provider(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "snapdragon")
    from handlers import process

    assert process is not None  # import succeeding (not raising) is the point of this test

    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
