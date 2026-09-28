"""
POST /emergency/plan

Body: {"situation": "lost_wallet"}

Flow: Lambda -> retrieve user's stored documents/profile from DynamoDB
      -> Bedrock (reasoning over ONLY that data) -> structured plan
      -> deterministic validation (every referenced document must
      actually exist and belong to this user; steps get re-sorted by
      priority) -> response.

This endpoint is organizational/decision-support only: it never
performs a transaction, never contacts anyone, and never gives medical
diagnosis/treatment advice (enforced via the system prompt in
bedrock_client.py / the fixed templates in local_reasoning.py, and by
validate_plan() below, which strips any step referencing a document_id
that isn't actually the user's).

The actual reasoning happens behind lib/ai_provider.py, which
dispatches to either the real Bedrock integration or the local,
fully-offline rule-based engine depending on LIFELINE_AI_PROVIDER —
see lib/ai_provider.py for why.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import dynamo_store, ai_provider
from lib.situations import SITUATIONS
from lib.auth_utils import get_user_id, UnauthorizedError
from lib.http import response, error, parse_body


def _build_user_context(user_id: str) -> dict:
    docs = dynamo_store.list_documents(user_id)
    profile = dynamo_store.get_profile(user_id) or {}
    # Only pass fields the model needs — never raw S3 keys/internal metadata.
    trimmed_docs = [{
        "document_id": d.get("document_id"),
        "document_type": d.get("document_type"),
        "title": d.get("title"),
        "provider": d.get("provider"),
        "expiry_date": d.get("expiry_date"),
        "status": d.get("status"),
    } for d in docs if d.get("status") == "processed"]
    return {
        "documents": trimmed_docs,
        "emergency_contact": profile.get("emergency_contact"),
    }


def validate_plan(raw_plan: dict, valid_document_ids: set[str]) -> dict:
    """
    Deterministic guardrail over the model's draft: drop any reference
    to a document that isn't actually this user's, keep step ordering
    from the model but re-number sequentially, and always carry the
    non-negotiable disclaimer regardless of what the model returned.

    Defensive against a malformed model response (wrong types for a
    field, a step that isn't an object, etc) — never raises; anything
    that doesn't look right for a given field is just dropped rather
    than crashing the whole plan.
    """
    raw_steps = raw_plan.get("steps", [])
    if not isinstance(raw_steps, list):
        raw_steps = []

    steps = []
    for i, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            continue
        src_ids_raw = step.get("source_document_ids", [])
        src_ids = [d for d in src_ids_raw if isinstance(d, str) and d in valid_document_ids] \
            if isinstance(src_ids_raw, list) else []
        steps.append({
            "order": i,
            "action": str(step.get("action", "")).strip(),
            "why": str(step.get("why", "")).strip(),
            "source_document_ids": src_ids,
        })

    raw_relevant = raw_plan.get("relevant_documents", [])
    relevant = [d for d in raw_relevant if isinstance(d, str) and d in valid_document_ids] \
        if isinstance(raw_relevant, list) else []

    raw_missing = raw_plan.get("missing_information", [])
    missing = [str(m) for m in raw_missing] if isinstance(raw_missing, list) else []

    return {
        "situation": str(raw_plan.get("situation", "")),
        "summary": str(raw_plan.get("summary", "")),
        "steps": steps,
        "relevant_documents": relevant,
        "missing_information": missing,
        "disclaimer": (
            "LifeLine prepares information and next steps for you to act on. "
            "It does not diagnose medical conditions, provide treatment advice, "
            "move money, or contact anyone on your behalf."
        ),
    }


def handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))

    try:
        body = parse_body(event)
    except Exception:
        return error(400, "Invalid JSON body")

    situation_key = body.get("situation")
    if situation_key not in SITUATIONS:
        return error(400, f"situation must be one of {list(SITUATIONS)}")

    context_data = _build_user_context(user_id)
    valid_ids = {d["document_id"] for d in context_data["documents"]}

    result = ai_provider.draft_emergency_plan(
        situation=SITUATIONS[situation_key], user_data=context_data
    )
    if not result.get("ok"):
        return error(502, f"Could not generate a plan right now: {result.get('error')}",
                     retryable=result.get("retryable", True))

    # Reuse the same robust JSON parsing as document extraction (handles
    # markdown fences and stray preamble text the model wasn't supposed
    # to add).
    from lib.schema import _strip_code_fences, _extract_first_json_object

    cleaned = _strip_code_fences(result["text"])
    try:
        raw_plan = json.loads(cleaned)
    except json.JSONDecodeError:
        candidate = _extract_first_json_object(cleaned)
        if candidate is None:
            return error(502, "Plan generation returned an unexpected format. Please retry.", retryable=True)
        try:
            raw_plan = json.loads(candidate)
        except json.JSONDecodeError:
            return error(502, "Plan generation returned an unexpected format. Please retry.", retryable=True)

    if not isinstance(raw_plan, dict):
        return error(502, "Plan generation returned an unexpected format. Please retry.", retryable=True)

    plan = validate_plan(raw_plan, valid_ids)
    plan["document_count_considered"] = len(context_data["documents"])
    return response(200, plan)
