import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws


def _create_table():
    os.environ["LIFELINE_TABLE"] = "lifeline-decimal-test"  # dynamo_store reads this per-call
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="lifeline-decimal-test",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@mock_aws
def test_put_document_with_float_confidence_does_not_raise():
    from lib import dynamo_store

    _create_table()
    # This is exactly the shape process.py writes after a successful
    # Bedrock extraction — confidence is a Python float from pydantic.
    dynamo_store.put_document("user-a", "doc-1", {
        "title": "Insurance Policy",
        "document_type": "insurance",
        "confidence": 0.93,
        "expiry_date": "2026-10-14",
        "important_dates": [{"date": "2026-10-14", "type": "expiry", "description": "Policy expires"}],
    })
    doc = dynamo_store.get_document("user-a", "doc-1")
    assert doc["confidence"] == 0.93
    assert isinstance(doc["confidence"], float)


@mock_aws
def test_update_document_status_with_float_confidence_does_not_raise():
    from lib import dynamo_store

    _create_table()
    dynamo_store.put_document("user-a", "doc-1", {"title": "x", "document_type": "other"})
    dynamo_store.update_document_status("user-a", "doc-1", "processed", {"confidence": 0.42})
    doc = dynamo_store.get_document("user-a", "doc-1")
    assert doc["confidence"] == 0.42


@mock_aws
def test_list_documents_round_trips_floats_correctly():
    from lib import dynamo_store

    _create_table()
    dynamo_store.put_document("user-a", "doc-1", {"title": "x", "document_type": "other", "confidence": 0.815})
    docs = dynamo_store.list_documents("user-a")
    assert docs[0]["confidence"] == 0.815
