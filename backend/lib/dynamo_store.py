"""
DynamoDB access layer for LifeLine.

Single-table design.

Table: lifeline (see infrastructure/template.yaml)
  PK (partition key)   SK (sort key)                 Item
  USER#<user_id>       DOC#<document_id>              document metadata + extraction
  USER#<user_id>       EVENT#<date>#<document_id>     attention/reminder event
  USER#<user_id>       PROFILE                        emergency contact / profile info

GSI1 (gsi1pk / gsi1sk): supports scanning "all documents with an
important date in range X" for the EventBridge reminder sweep without
a full table scan.
  gsi1pk = "DATE#<expiry_date>"
  gsi1sk = "USER#<user_id>#DOC#<document_id>"

Every read/write takes user_id explicitly and only ever touches that
user's partition — this is what user isolation rests on, enforced in
code (see tests/test_auth_isolation).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

def _table():
    # Read the table name at call time, not import time: Lambda always
    # sets this once per cold start so it doesn't matter there, but
    # binding it as a module-level constant breaks test isolation (a
    # test file that sets LIFELINE_TABLE after this module has already
    # been imported elsewhere in the same test session would silently
    # talk to the wrong table).
    table_name = os.environ.get("LIFELINE_TABLE", "lifeline-dev")
    return boto3.resource("dynamodb").Table(table_name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dynamo_safe(value):
    """
    DynamoDB's boto3 resource API rejects Python float (it can't
    represent binary floats losslessly) and requires Decimal instead.
    Bedrock's extraction includes a float `confidence` field, so every
    write path needs this — without it, storing a processed document
    raises TypeError at write time and the pipeline silently never
    reaches "processed". Recurses through dicts/lists; leaves other
    types untouched.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo_safe(v) for v in value]
    return value


def _from_dynamo_safe(value):
    """Inverse of _to_dynamo_safe for reads — Decimal back to float/int."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo_safe(v) for v in value]
    return value


def put_document(user_id: str, document_id: str, item: dict) -> dict:
    row = {
        "PK": f"USER#{user_id}",
        "SK": f"DOC#{document_id}",
        "document_id": document_id,
        "user_id": user_id,
        "created_at": _now(),
        "updated_at": _now(),
        **item,
    }
    if item.get("expiry_date"):
        row["gsi1pk"] = f"DATE#{item['expiry_date']}"
        row["gsi1sk"] = f"USER#{user_id}#DOC#{document_id}"
    _table().put_item(Item=_to_dynamo_safe(row))
    return row


def get_document(user_id: str, document_id: str) -> dict | None:
    resp = _table().get_item(Key={"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"})
    item = resp.get("Item")
    return _from_dynamo_safe(item) if item is not None else None


def list_documents(user_id: str) -> list[dict]:
    resp = _table().query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("DOC#")
    )
    return [_from_dynamo_safe(i) for i in resp.get("Items", [])]


def update_document_status(user_id: str, document_id: str, status: str, extra: dict | None = None) -> None:
    extra = _to_dynamo_safe(extra or {})
    expr_names = {"#s": "status", "#u": "updated_at"}
    expr_values = {":s": status, ":u": _now()}
    set_clause = "#s = :s, #u = :u"
    for k, v in extra.items():
        expr_names[f"#{k}"] = k
        expr_values[f":{k}"] = v
        set_clause += f", #{k} = :{k}"
    _table().update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"},
        UpdateExpression=f"SET {set_clause}",
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def put_profile(user_id: str, profile: dict) -> dict:
    row = {"PK": f"USER#{user_id}", "SK": "PROFILE", "user_id": user_id, "updated_at": _now(), **profile}
    _table().put_item(Item=_to_dynamo_safe(row))
    return row


def get_profile(user_id: str) -> dict | None:
    resp = _table().get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    item = resp.get("Item")
    return _from_dynamo_safe(item) if item is not None else None


def documents_expiring_between(start_date: str, end_date: str) -> list[dict]:
    """
    Used by the EventBridge-triggered reminder sweep. Queries GSI1 for
    each date in range rather than scanning the whole table.
    NOTE: for MVP scale (hackathon demo) this loops per-day; a
    production version would batch this differently.
    """
    from datetime import timedelta

    table = _table()
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    items = []
    d = start
    while d <= end:
        resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"DATE#{d.isoformat()}"),
        )
        items.extend(resp.get("Items", []))
        d += timedelta(days=1)
    return [_from_dynamo_safe(i) for i in items]


def put_event(user_id: str, document_id: str, event_date: str, event: dict) -> None:
    row = {
        "PK": f"USER#{user_id}",
        "SK": f"EVENT#{event_date}#{document_id}",
        "user_id": user_id,
        "document_id": document_id,
        "created_at": _now(),
        **event,
    }
    _table().put_item(Item=_to_dynamo_safe(row))


def list_events(user_id: str) -> list[dict]:
    resp = _table().query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("EVENT#")
    )
    return [_from_dynamo_safe(i) for i in resp.get("Items", [])]
