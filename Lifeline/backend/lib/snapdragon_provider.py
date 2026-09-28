"""
On-device AI provider for LIFELINE_AI_PROVIDER=snapdragon.

Scope of what is actually new here, stated plainly:

- Image documents: text is recognized on-device via lib/onnx_ocr.py
  (a real ONNX Runtime neural-network OCR pipeline — detection +
  angle-classification + recognition — instead of lib/ocr.py's
  Tesseract), with Qualcomm Snapdragon NPU acceleration via
  `QNNExecutionProvider` when the execution mode allows it (see
  lib/qnn_execution.py). This is the genuine new on-device AI
  component.
- PDF documents: text already comes from a text layer
  (lib/pdf_extract.py, unchanged) — there is no OCR step to replace,
  so this path is identical to LIFELINE_AI_PROVIDER=local.
- Structuring recognized/extracted text into the document schema
  (document_type, dates, amount, provider, ...) reuses
  lib/local_reasoning.py's existing deterministic regex/keyword logic
  unchanged. That logic is not a neural network and this module does
  not claim otherwise — the honest claim is narrower: "this provider
  replaces Tesseract's OCR with an on-device ONNX model," not "this
  provider adds AI to structuring."
- draft_emergency_plan() is not part of the Snapdragon story at all —
  it delegates straight to lib/local_reasoning.py's existing
  deterministic template engine, unchanged, purely so this provider
  satisfies the same two-function contract as lib/bedrock_client.py
  and lib/local_reasoning.py that lib/ai_provider.py dispatches to.

See docs/snapdragon-optimization.md for exactly what is verified on
which hardware, and runtime_status() below (also exposed via
backend/tools/snapdragon_demo.py) for how to check, on any given
machine, whether QNN/NPU execution is actually active right now rather
than assumed.
"""
from __future__ import annotations

import json
from typing import Any

from lib import onnx_ocr
from lib.local_reasoning import _extract_from_text, draft_emergency_plan as _local_draft_emergency_plan


def extract_document(*, text: str | None = None, image_bytes: bytes | None = None,
                      image_media_type: str = "image/png") -> dict:
    """
    Same {"ok": bool, "text": "<json>", ...} contract as
    lib/bedrock_client.py and lib/local_reasoning.py. Only the image
    path differs from LIFELINE_AI_PROVIDER=local: OCR runs through
    lib/onnx_ocr.py's on-device ONNX model (QNN-accelerated when
    available and permitted by LIFELINE_OCR_EXECUTION_MODE) instead of
    Tesseract.
    """
    if image_bytes is not None:
        try:
            recognized_text = onnx_ocr.extract_text_from_image(image_bytes)
        except onnx_ocr.OnnxOcrError as e:
            return {"ok": False, "error": str(e), "retryable": False}
        extracted = _extract_from_text(recognized_text)
    else:
        extracted = _extract_from_text(text or "")

    return {"ok": True, "text": json.dumps(extracted)}


def runtime_status() -> dict[str, Any]:
    """
    Diagnostic snapshot of the on-device OCR execution mode/provider
    in use by this provider — see lib/onnx_ocr.py.runtime_status() and
    lib/qnn_execution.py.diagnostics() for the fields returned. Not
    part of the shared ai_provider two-function contract (bedrock/local
    have no equivalent notion of "which execution provider"); callers
    that want this should import lib.snapdragon_provider directly, as
    backend/tools/snapdragon_demo.py does.
    """
    return onnx_ocr.runtime_status()


def draft_emergency_plan(*, situation: str, user_data: dict) -> dict:
    """
    Unchanged from LIFELINE_AI_PROVIDER=local — see module docstring
    for why plan drafting is intentionally out of scope for the
    Snapdragon/on-device-AI change.
    """
    return _local_draft_emergency_plan(situation=situation, user_data=user_data)
