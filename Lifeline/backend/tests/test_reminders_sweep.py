import os
import sys
from datetime import date, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws


def _create_table():
    os.environ["LIFELINE_TABLE"] = "lifeline-reminders-test"  # dynamo_store reads this per-call
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="lifeline-reminders-test",
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


@mock_aws
def test_sweep_writes_events_for_upcoming_and_overdue_documents():
    from lib import dynamo_store
    from handlers import reminders

    _create_table()
    today = date.today()
    soon = (today + timedelta(days=5)).isoformat()
    overdue = (today - timedelta(days=10)).isoformat()

    dynamo_store.put_document("user-a", "doc-soon", {
        "title": "Insurance", "document_type": "insurance", "expiry_date": soon, "confidence": 0.9,
    })
    dynamo_store.put_document("user-a", "doc-overdue", {
        "title": "Warranty", "document_type": "warranty", "expiry_date": overdue, "confidence": 0.9,
    })

    result = reminders.handler({}, None)
    assert result["statusCode"] == 200

    events = dynamo_store.list_events("user-a")
    event_doc_ids = {e["document_id"] for e in events}
    assert "doc-soon" in event_doc_ids
    assert "doc-overdue" in event_doc_ids

    overdue_event = next(e for e in events if e["document_id"] == "doc-overdue")
    assert overdue_event["priority_level"] == "urgent"


@mock_aws
def test_sweep_ignores_documents_without_expiry_date():
    from lib import dynamo_store
    from handlers import reminders

    _create_table()
    dynamo_store.put_document("user-a", "doc-no-date", {"title": "Certificate", "document_type": "certificate"})

    result = reminders.handler({}, None)
    assert result["statusCode"] == 200

    events = dynamo_store.list_events("user-a")
    assert events == []
