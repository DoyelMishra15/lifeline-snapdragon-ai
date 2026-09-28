"""
Triggered on a schedule by Amazon EventBridge (see infrastructure/template.yaml
— a `rate(1 day)` rule for the MVP demo).

Not an API Gateway handler — invoked directly by EventBridge, so
there's no HTTP event/auth context here. Scans a window from 90 days
in the past (to keep re-flagging anything expired and still
unrenewed) through 90 days in the future via the GSI (no full table
scan), and (re)writes an attention EVENT# record for each so the
dashboard can show real, EventBridge-produced attention data instead
of only recomputing priority client-side on every page load.

This is deliberately the whole "notification ecosystem" for the MVP:
the event mechanism is real and demoable (events appear + are visible
in the dashboard/DynamoDB), but actually sending an email/SMS is out
of scope for the hackathon timeline — see docs/limitations.md.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import dynamo_store
from lib.priority_engine import classify_item

FORWARD_WINDOW_DAYS = 90
# Also sweep backward: an item that already expired and was never
# renewed is still urgent and should keep generating attention events,
# not silently drop out of the sweep the day after it lapses. Kept
# equal to the forward window so a daily sweep stays well within the
# Lambda timeout (each day in range is one GSI query — see
# dynamo_store.documents_expiring_between's per-day-loop note).
BACKWARD_WINDOW_DAYS = 90


def handler(event, context):
    today = date.today()
    start = today - timedelta(days=BACKWARD_WINDOW_DAYS)
    end = today + timedelta(days=FORWARD_WINDOW_DAYS)

    items = dynamo_store.documents_expiring_between(start.isoformat(), end.isoformat())

    created = 0
    for item in items:
        user_id = item.get("user_id")
        document_id = item.get("document_id")
        expiry_date = item.get("expiry_date") or item.get("gsi1pk", "").replace("DATE#", "")
        if not (user_id and document_id and expiry_date):
            continue

        result = classify_item(
            expiry_date=expiry_date,
            document_type=item.get("document_type", "other"),
            has_actions=bool(item.get("actions")),
            confidence=item.get("confidence", 1.0),
            today=today,
        )

        dynamo_store.put_event(user_id, document_id, expiry_date, {
            "event_type": "attention_sweep",
            "document_id": document_id,
            "title": item.get("title"),
            "priority_level": result.level.value,
            "reason": result.reason,
        })
        created += 1

    return {"statusCode": 200, "body": f"Swept {len(items)} item(s), wrote {created} attention event(s)."}
