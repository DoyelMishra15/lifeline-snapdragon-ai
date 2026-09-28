"""
AI provider dispatch.

LifeLine's document extraction and emergency-plan generation are used
through this module, never by calling bedrock_client.py or
local_reasoning.py directly from a handler. That keeps the choice of
"which AI layer actually runs" in exactly one place, controlled by the
LIFELINE_AI_PROVIDER environment variable:

- "local"   -> lib/local_reasoning.py — a fully deterministic, offline
               extraction + emergency-plan engine (regex/keyword based
               document parsing, template-based plan drafting, OCR via
               Tesseract for images through lib/ocr.py). No AWS
               account, credentials, or network calls of any kind.
               This is what infrastructure/env.local.json sets for the
               GitHub Codespaces / SAM-local + LocalStack workflow,
               since Amazon Bedrock cannot run inside LocalStack and
               would otherwise require a real AWS account and billing.
- "bedrock" -> lib/bedrock_client.py — the real Amazon Bedrock
               integration, unchanged from the original architecture.
               This is what infrastructure/template.yaml sets as the
               default for an actual `sam deploy` to AWS.
- "snapdragon" -> lib/snapdragon_provider.py — on-device extraction:
               images go through lib/onnx_ocr.py's ONNX Runtime OCR
               pipeline instead of Tesseract; everything else
               (structuring, plan drafting) reuses lib/local_reasoning.py
               unchanged. See docs/snapdragon-optimization.md for what
               is verified versus what still needs real Snapdragon
               hardware validation. Requires
               backend/requirements-snapdragon.txt to be installed;
               not part of the default Lambda deployment.

All three backends expose the exact same two functions with the exact
same {"ok": bool, "text": "...", "retryable": bool} contract, so
handlers/process.py and handlers/emergency.py never need to know or
care which one is running underneath.
"""
from __future__ import annotations

import os


def current_provider() -> str:
    # Read at call time, not import time. Binding this as a module-level
    # constant caused real cross-test contamination (a test reloading
    # this module to exercise "local" mode would leak that choice into
    # every later test in the same process, silently swapping out
    # Bedrock for the local engine) and would carry the same risk in
    # Lambda if the env var were ever changed without a cold start.
    return os.environ.get("LIFELINE_AI_PROVIDER", "bedrock").strip().lower()


def _backend():
    provider = current_provider()
    if provider == "local":
        from lib import local_reasoning
        return local_reasoning
    if provider == "snapdragon":
        from lib import snapdragon_provider
        return snapdragon_provider
    from lib import bedrock_client
    return bedrock_client


def extract_document(*, text: str | None = None, image_bytes: bytes | None = None,
                      image_media_type: str = "image/png") -> dict:
    return _backend().extract_document(text=text, image_bytes=image_bytes, image_media_type=image_media_type)


def draft_emergency_plan(*, situation: str, user_data: dict) -> dict:
    return _backend().draft_emergency_plan(situation=situation, user_data=user_data)


def runtime_status() -> dict | None:
    """
    Diagnostic snapshot of the currently selected provider's execution
    backend — currently only meaningful for "snapdragon" (which
    provider/QNN status lib/qnn_execution.py resolved; see
    lib/snapdragon_provider.py.runtime_status()). "local" and "bedrock"
    have no equivalent notion of an execution provider, so this
    returns None for them rather than fabricating a status. Not part
    of the core two-function contract every backend must implement —
    this is an optional extra, checked for with getattr() rather than
    required.
    """
    backend = _backend()
    status_fn = getattr(backend, "runtime_status", None)
    if status_fn is None:
        return None
    return status_fn()
