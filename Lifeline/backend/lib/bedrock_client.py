"""
Amazon Bedrock wrapper.

Two responsibilities only:
  1. extract_document() — turn a document (text or image bytes) into
     the structured JSON described in schema.py.
  2. draft_emergency_plan() — given a situation + the user's already
     -stored structured data, draft a prioritized, source-referenced
     action plan. This is reasoning/drafting only; the actual
     prioritization/ranking of plan steps is re-validated by
     deterministic code, and the model is explicitly instructed not to
     invent facts that are not present in the provided context.

Both fail gracefully: on any Bedrock error they return a structured
failure the caller can store/display instead of raising into the
Lambda handler.
"""
from __future__ import annotations

import base64
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

# Claude Sonnet 4.6 via Bedrock's global cross-region inference profile —
# routes to whichever region has capacity, so it works the same regardless
# of which region LifeLine itself is deployed in. Override with a
# region-pinned profile (e.g. "us.anthropic.claude-sonnet-4-6") or a
# different model entirely via LIFELINE_BEDROCK_MODEL_ID if your account's
# model access or data-residency requirements need that.
MODEL_ID = os.environ.get("LIFELINE_BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Errors worth one short retry (transient capacity/throttling), vs. errors
# that will never succeed on retry (bad request, access denied, etc).
_RETRYABLE_ERROR_CODES = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}
_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 1.5

EXTRACTION_SYSTEM_PROMPT = """You extract structured information from personal documents \
(insurance policies, IDs, warranties, bills, certificates, etc).

Rules:
- Respond with ONLY a single JSON object. No prose, no markdown fences.
- Never invent facts that are not present in the document. If a field \
is not present, omit it or use null.
- Dates must be in YYYY-MM-DD format.
- "confidence" (0.0-1.0) must reflect your genuine certainty about the \
extraction as a whole — lower it if the document is blurry, partial, \
ambiguous, or if you are guessing at a field.
- If the document text is unreadable or clearly not a personal document, \
set document_type to "other", confidence to a low value, and explain \
in "warnings".

Return JSON matching this shape:
{
  "document_type": "insurance|identity|passport|warranty|bill|subscription|certificate|medical|financial|legal|other",
  "title": "string",
  "provider": "string or null",
  "expiry_date": "YYYY-MM-DD or null",
  "important_dates": [{"date": "YYYY-MM-DD", "type": "expiry|renewal|payment_due|issue", "description": "string"}],
  "amount": "string or null",
  "actions": ["string"],
  "relevant_entities": ["string"],
  "warnings": ["string"],
  "confidence": 0.0
}"""

EMERGENCY_SYSTEM_PROMPT = """You are LifeLine's emergency/situation assistant.

You help a user organize and prioritize action AFTER something has \
gone wrong (lost wallet, lost phone, hospital admission, travel \
emergency, etc). You are a decision-support tool, not an emergency \
service.

Hard rules:
- Base every fact ONLY on the user-data JSON provided to you. Never \
invent a document, date, account, or contact that is not in it.
- If information needed for a step is missing from the provided data, \
say so explicitly instead of guessing.
- Do NOT give medical diagnosis or medical treatment advice.
- Do NOT claim to perform financial transactions or to have contacted \
anyone — you only prepare information and steps for the human to act on.
- Every fact you surface should reference which stored document it \
came from (by title/document_id) when applicable.
- Respond with ONLY a single JSON object, no prose, no markdown fences.

Return JSON matching this shape:
{
  "situation": "string",
  "summary": "one sentence",
  "steps": [
    {"order": 1, "action": "string", "why": "string", "source_document_ids": ["doc-id"]}
  ],
  "relevant_documents": ["doc-id"],
  "missing_information": ["string"],
  "disclaimer": "string"
}"""


def _client():
    return boto3.client("bedrock-runtime", region_name=REGION)


def _invoke(system_prompt: str, user_content: list[dict], max_tokens: int = 1500) -> dict:
    """
    Call Bedrock's InvokeModel with the Anthropic Messages request format.
    Retries once on transient errors (throttling/capacity), never on
    permanent ones (bad request, access denied, model not found) — and
    never raises: every failure mode returns {"ok": False, "error": ...,
    "retryable": bool} so callers can decide whether to offer a retry
    button versus surface a hard failure.
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }

    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = _client().invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = json.loads(resp["body"].read())

            if payload.get("type") == "error":
                # Bedrock/Anthropic returned a 200 with an error envelope
                # (happens for some content-policy or overload cases).
                return {"ok": False, "error": payload.get("error", {}).get("message", "Model returned an error"),
                        "retryable": False}

            text = "".join(
                block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text"
            )
            if not text.strip():
                return {"ok": False, "error": "Model returned an empty response", "retryable": True}
            return {"ok": True, "text": text}

        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            last_error = e.response.get("Error", {}).get("Message", str(e))
            if code in _RETRYABLE_ERROR_CODES and attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            if code == "AccessDeniedException":
                last_error = (
                    f"Bedrock access denied for model '{MODEL_ID}'. In the AWS console, go to "
                    "Bedrock > Model access and request access to this model in this region."
                )
            elif code == "ValidationException":
                last_error = f"Bedrock rejected the request: {last_error}"
            return {"ok": False, "error": last_error, "retryable": code in _RETRYABLE_ERROR_CODES}

        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"Could not parse Bedrock response: {e}", "retryable": True}

        except Exception as e:  # noqa: BLE001 - must never let an unexpected error crash the pipeline
            last_error = str(e)
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            return {"ok": False, "error": last_error, "retryable": True}

    return {"ok": False, "error": last_error or "Unknown Bedrock error", "retryable": True}


def extract_document(*, text: str | None = None, image_bytes: bytes | None = None,
                      image_media_type: str = "image/png") -> dict:
    """Extract structured info from either document text or an image."""
    if image_bytes is not None:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                },
            },
            {"type": "text", "text": "Extract the structured information from this document image."},
        ]
    else:
        content = [{"type": "text", "text": f"Extract the structured information from this document:\n\n{text}"}]

    return _invoke(EXTRACTION_SYSTEM_PROMPT, content, max_tokens=1200)


def draft_emergency_plan(*, situation: str, user_data: dict) -> dict:
    prompt = (
        f"Situation selected by user: {situation}\n\n"
        f"User's stored data (documents, dates, profile — the ONLY facts "
        f"you may reference):\n{json.dumps(user_data, default=str)}"
    )
    content = [{"type": "text", "text": prompt}]
    return _invoke(EMERGENCY_SYSTEM_PROMPT, content, max_tokens=1500)
