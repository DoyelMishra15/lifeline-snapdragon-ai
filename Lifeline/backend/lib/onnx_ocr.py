"""
Local, on-device OCR via an ONNX Runtime document-OCR pipeline.

Uses `rapidocr-onnxruntime` (PyPI), which bundles the PaddleOCR
PP-OCRv4 detection + angle-classification + recognition models,
pre-exported to ONNX, inside the package itself — no model download at
import time or call time, no network access required to run this
module.

This is the OCR path for LIFELINE_AI_PROVIDER=snapdragon (see
lib/snapdragon_provider.py and lib/ai_provider.py). It is intentionally
a separate module from lib/ocr.py (Tesseract), which remains exactly
as it was and continues to serve LIFELINE_AI_PROVIDER=local.

Execution modes (see lib/qnn_execution.py for the full contract):

- "auto" (default) — prefer QNNExecutionProvider (Snapdragon NPU),
  transparently fall back to CPUExecutionProvider when QNN isn't
  registered in this onnxruntime build or fails for these models. This
  is what makes the exact same code run in Codespaces/Linux (CPU) and
  on a real Windows-on-Snapdragon device (NPU) with no code change —
  only LIFELINE_QNN_* environment variables differ.
- "qnn" — require QNNExecutionProvider. Raises OnnxOcrError (never
  silently uses CPU) if QNN isn't available, or if a session can't
  actually be created under it.
- "cpu" — always CPUExecutionProvider. For development/testing on
  machines with no NPU at all (e.g. Codespaces/Linux/x86_64).

Set via the LIFELINE_OCR_EXECUTION_MODE environment variable, or pass
`mode=` explicitly to the functions below (mainly for tests/tools).

The actual QNN session wiring lives in lib/rapidocr_qnn_session.py —
see its module docstring for why rapidocr's own session creation has
to be substituted rather than configured through its public API.
"""
from __future__ import annotations

from typing import Any

from lib import qnn_execution

# Lazy singleton: loading the three ONNX models is the expensive part
# of startup, so do it once per process. Keyed by execution mode so
# that switching LIFELINE_OCR_EXECUTION_MODE (or passing an explicit
# `mode=`) between calls — as the test suite and tools/*.py do —
# rebuilds the engine instead of silently reusing one built under a
# different mode.
_engine = None
_engine_mode: str | None = None


class OnnxOcrError(Exception):
    """
    Raised when on-device OCR cannot run at all: missing dependency,
    an execution-mode configuration error, or a genuinely corrupt/
    unreadable image. A valid image with no recognizable text is not
    an error — see extract_text_from_image().

    `.reason`, when set, mirrors lib/qnn_execution.py's
    ExecutionModeError reasons (REASON_INVALID_MODE,
    REASON_QNN_UNAVAILABLE, REASON_QNN_SESSION_FAILED) so callers can
    distinguish "QNN unavailable" from "QNN configured but the
    model/session failed" without parsing the message text.
    """

    def __init__(self, message: str, *, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


def _get_engine(mode: str | None = None):
    global _engine, _engine_mode

    try:
        resolved = qnn_execution.resolve_execution_mode(mode)
    except qnn_execution.ExecutionModeError as e:
        raise OnnxOcrError(str(e), reason=e.reason) from e

    if _engine is not None and _engine_mode == resolved:
        return _engine

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:  # pragma: no cover - packaging issue, not a runtime path
        raise OnnxOcrError(
            "on-device OCR dependencies not installed. Run "
            "`pip install -r backend/requirements-snapdragon.txt` to use "
            "LIFELINE_AI_PROVIDER=snapdragon."
        ) from e

    from lib import rapidocr_qnn_session

    rapidocr_qnn_session.patch_rapidocr_sessions()

    try:
        with qnn_execution.use_mode(resolved):
            engine = RapidOCR()
    except qnn_execution.ExecutionModeError as e:
        raise OnnxOcrError(str(e), reason=e.reason) from e

    _engine = engine
    _engine_mode = resolved
    return _engine


def available_execution_providers() -> list[str]:
    """
    The ONNX Runtime execution providers actually available in this
    process (e.g. ["CPUExecutionProvider"] on a Codespaces/Linux/
    x86_64 box; ["QNNExecutionProvider", "CPUExecutionProvider", ...]
    on Windows-on-Snapdragon with `onnxruntime-qnn` installed and the
    QNN backend libraries reachable). Never assumed — always queried
    live from onnxruntime.
    """
    try:
        return qnn_execution.available_providers()
    except ImportError as e:  # pragma: no cover - packaging issue, not a runtime path
        raise OnnxOcrError(
            "onnxruntime not installed. Run "
            "`pip install -r backend/requirements-snapdragon.txt`."
        ) from e


def runtime_status(mode: str | None = None) -> dict[str, Any]:
    """
    A JSON-serializable snapshot of the current OCR execution
    situation: requested/resolved mode, ONNX Runtime providers actually
    registered, whether QNN is registered, and whether the *loaded*
    engine (if one has been built in this process) actually ended up
    running on QNN. Used by backend/tools/snapdragon_demo.py and
    backend/tools/onnx_ocr_benchmark.py to report honestly what
    backend is in use, and safe to expose from an API/health endpoint.
    """
    try:
        status = qnn_execution.diagnostics(mode)
    except qnn_execution.ExecutionModeError as e:
        raise OnnxOcrError(str(e), reason=e.reason) from e
    status["engine_loaded"] = _engine is not None
    status["engine_mode"] = _engine_mode
    status["engine_active_provider"] = None
    if _engine is not None:
        # All three model sessions (det/cls/rec) are built under the
        # same mode/provider list in one RapidOCR() construction (see
        # _get_engine above), so any one of them is representative.
        status["engine_active_provider"] = getattr(
            _engine.text_rec.session, "active_provider", None
        )
    return status


def extract_text_from_image(image_bytes: bytes, *, mode: str | None = None) -> str:
    """
    Run the on-device ONNX OCR pipeline on raw image bytes and return
    the recognized text, one recognized line per output line — the
    same shape lib/ocr.py's Tesseract wrapper returns, so
    lib/snapdragon_provider.py can feed the result straight into
    lib/local_reasoning.py's existing text-parsing logic unchanged.

    `mode` overrides LIFELINE_OCR_EXECUTION_MODE for this call (mainly
    for tests/tools) — see the module docstring for what "auto"/"qnn"/
    "cpu" each guarantee.

    Raises OnnxOcrError when OCR cannot run at all (missing
    dependency, corrupt/unreadable image, or the requested execution
    mode can't be honored — see OnnxOcrError.reason). A valid image
    with no recognizable text returns an empty string, exactly like
    lib/ocr.py — that is not an error, it's a legitimate low/no-text
    result for the caller's confidence scoring to handle.
    """
    engine = _get_engine(mode)
    try:
        result, _elapse = engine(image_bytes)
    except Exception as e:  # noqa: BLE001
        raise OnnxOcrError(f"On-device OCR failed: {e}") from e

    if not result:
        return ""
    lines = [str(item[1]) for item in result if len(item) >= 2]
    return "\n".join(lines).strip()
