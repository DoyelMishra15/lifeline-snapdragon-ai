import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import json
import boto3
from moto import mock_aws


def _create_table():
    os.environ["LIFELINE_TABLE"] = "lifeline-doclist-test"  # dynamo_store reads this per-call
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="lifeline-doclist-test",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "gsi1sk", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "gsi1",
            "KeySchema": [
                {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )


def _auth_event(user_id):
    return {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}}}


@mock_aws
def test_list_handler_requires_auth():
    from handlers import documents
    resp = documents.list_handler({"requestContext": {}}, None)
    assert resp["statusCode"] == 401


@mock_aws
def test_list_handler_returns_documents_conflicts_and_recent_events():
    from lib import dynamo_store
    from handlers import documents
    from handlers import reminders

    _create_table()
    dynamo_store.put_document("user-a", "doc-1", {
        "title": "Insurance", "document_type": "insurance", "status": "processed",
        "provider": "Acme", "expiry_date": "2026-10-01", "confidence": 0.9,
    })
    reminders.handler({}, None)  # populate a real attention event via the sweep

    resp = documents.list_handler(_auth_event("user-a"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["documents"]) == 1
    assert body["documents"][0]["document_id"] == "doc-1"
    assert "priority" in body["documents"][0]
    assert body["conflicts"] == []
    assert len(body["recent_events"]) >= 1
    assert body["recent_events"][0]["document_id"] == "doc-1"


@mock_aws
def test_list_handler_never_returns_another_users_documents():
    from lib import dynamo_store
    from handlers import documents

    _create_table()
    dynamo_store.put_document("user-a", "doc-a", {"title": "A doc", "document_type": "other", "status": "processed"})
    dynamo_store.put_document("user-b", "doc-b", {"title": "B doc", "document_type": "other", "status": "processed"})

    resp = documents.list_handler(_auth_event("user-a"), None)
    body = json.loads(resp["body"])
    assert [d["document_id"] for d in body["documents"]] == ["doc-a"]
