"""
GET /documents           -> list of user's documents, each with priority attached
GET /documents/{id}      -> single document detail + a fresh presigned source URL
"""
from __future__ import annotations

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import dynamo_store, s3_store
from lib.priority_engine import rank_documents
from lib.auth_utils import get_user_id, UnauthorizedError
from lib.http import response, error


RECENT_EVENTS_LIMIT = 20


def _detect_conflicts(documents: list[dict]) -> list[dict]:
    """
    Flag when two processed documents disagree on the same provider's
    expiry date for the same document_type — LifeLine must never
    silently pick one, per the provenance requirement.

    Only groups documents that have a *known* provider in common —
    two documents that both happen to have no provider detected are
    NOT the same real-world thing just because they share document_type
    (e.g. two different, unrelated "bill" uploads), so grouping by
    document_type alone would produce false-positive conflicts.
    """
    conflicts = []
    by_type_provider: dict[tuple, list[dict]] = {}
    for d in documents:
        if d.get("status") != "processed" or not d.get("expiry_date"):
            continue
        provider = (d.get("provider") or "").strip().lower()
        if not provider:
            continue
        key = (d.get("document_type"), provider)
        by_type_provider.setdefault(key, []).append(d)

    for key, docs in by_type_provider.items():
        dates = {d["expiry_date"] for d in docs}
        if len(dates) > 1:
            conflicts.append({
                "document_type": key[0],
                "provider": key[1],
                "conflicting_document_ids": [d["document_id"] for d in docs],
                "conflicting_dates": sorted(dates),
            })
    return conflicts


def list_handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))

    docs = dynamo_store.list_documents(user_id)
    ranked = rank_documents(docs)
    conflicts = _detect_conflicts(docs)

    # Surface what the EventBridge-driven reminder sweep has actually
    # produced (backend/handlers/reminders.py), rather than the
    # dashboard only ever re-deriving "recent activity" from the
    # document list on every page load.
    events = dynamo_store.list_events(user_id)
    recent_events = sorted(events, key=lambda e: e.get("created_at", ""), reverse=True)[:RECENT_EVENTS_LIMIT]

    return response(200, {"documents": ranked, "conflicts": conflicts, "recent_events": recent_events})


def get_handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))

    document_id = (event.get("pathParameters") or {}).get("document_id")
    doc = dynamo_store.get_document(user_id, document_id)
    if not doc:
        return error(404, "Document not found")
    if doc["user_id"] != user_id:
        return error(403, "Forbidden")

    source_url = None
    if doc.get("s3_key"):
        source_url = s3_store.get_document_source(doc["s3_key"], user_id)

    ranked = rank_documents([doc])[0]
    ranked["source_url"] = source_url
    return response(200, ranked)
