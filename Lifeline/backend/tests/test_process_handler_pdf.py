import io
import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws

reportlab = pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402
from pypdf import PdfWriter  # noqa: E402

TABLE_NAME = "lifeline-process-test"
BUCKET_NAME = "lifeline-process-test-bucket"


def _make_text_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 800, "Health Insurance Policy")
    c.drawString(72, 780, "Provider: Acme Insurance")
    c.save()
    return buf.getvalue()


def _make_blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _setup_aws():
    os.environ["LIFELINE_TABLE"] = TABLE_NAME
    os.environ["LIFELINE_DOCS_BUCKET"] = BUCKET_NAME

    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET_NAME)
    return s3


def _auth_event(user_id, document_id):
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}},
        "pathParameters": {"document_id": document_id},
    }


@mock_aws
def test_process_handler_extracts_text_pdf_end_to_end(monkeypatch):
    from lib import dynamo_store, s3_store
    from handlers import process

    s3 = _setup_aws()
    user_id, document_id = "user-a", "doc-1"
    key = s3_store.object_key(user_id, document_id, "policy.pdf")
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=_make_text_pdf(), ContentType="application/pdf")
    dynamo_store.put_document(user_id, document_id, {
        "title": "policy.pdf", "document_type": "other", "status": "uploaded",
        "s3_key": key, "content_type": "application/pdf", "filename": "policy.pdf",
    })

    # Stub Bedrock so this test exercises the real PDF-extraction + schema
    # -validation + storage path without a live AWS Bedrock call.
    def fake_extract_document(*, text=None, image_bytes=None, image_media_type=None):
        assert text is not None and "Acme Insurance" in text  # proves real PDF text reached Bedrock
        payload = {
            "document_type": "insurance", "title": "Health Insurance Policy", "provider": "Acme Insurance",
            "expiry_date": "2026-10-14", "important_dates": [], "actions": [], "warnings": [], "confidence": 0.9,
        }
        return {"ok": True, "text": json.dumps(payload)}

    monkeypatch.setattr("lib.bedrock_client.extract_document", fake_extract_document)

    resp = process.handler(_auth_event(user_id, document_id), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "processed"
    assert body["extraction"]["provider"] == "Acme Insurance"

    stored = dynamo_store.get_document(user_id, document_id)
    assert stored["status"] == "processed"
    assert stored["expiry_date"] == "2026-10-14"


@mock_aws
def test_process_handler_scanned_pdf_fails_as_needs_review_not_fabricated(monkeypatch):
    from lib import dynamo_store, s3_store
    from handlers import process

    s3 = _setup_aws()
    user_id, document_id = "user-a", "doc-2"
    key = s3_store.object_key(user_id, document_id, "scanned.pdf")
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=_make_blank_pdf(), ContentType="application/pdf")
    dynamo_store.put_document(user_id, document_id, {
        "title": "scanned.pdf", "document_type": "other", "status": "uploaded",
        "s3_key": key, "content_type": "application/pdf", "filename": "scanned.pdf",
    })

    called = {"bedrock": False}

    def fake_extract_document(**kwargs):
        called["bedrock"] = True
        return {"ok": True, "text": "{}"}

    monkeypatch.setattr("lib.bedrock_client.extract_document", fake_extract_document)

    resp = process.handler(_auth_event(user_id, document_id), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "needs_review"
    # The whole point of the fix: a scanned PDF must never be silently
    # sent to Bedrock as if it had real content.
    assert called["bedrock"] is False

    stored = dynamo_store.get_document(user_id, document_id)
    assert stored["status"] == "needs_review"


@mock_aws
def test_process_handler_corrupt_pdf_fails_gracefully():
    from lib import dynamo_store, s3_store
    from handlers import process

    s3 = _setup_aws()
    user_id, document_id = "user-a", "doc-3"
    key = s3_store.object_key(user_id, document_id, "corrupt.pdf")
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=b"not a real pdf", ContentType="application/pdf")
    dynamo_store.put_document(user_id, document_id, {
        "title": "corrupt.pdf", "document_type": "other", "status": "uploaded",
        "s3_key": key, "content_type": "application/pdf", "filename": "corrupt.pdf",
    })

    resp = process.handler(_auth_event(user_id, document_id), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "failed"

    stored = dynamo_store.get_document(user_id, document_id)
    assert stored["status"] == "failed"


@mock_aws
def test_process_handler_rejects_wrong_users_document():
    """
    Because the DynamoDB key is USER#<uid>/DOC#<id>, a lookup with a
    different user's id can never even find another user's document —
    the isolation is structural (a get_document() with the wrong user_id
    simply returns nothing), so this surfaces as 404, not 403. The
    doc["user_id"] != user_id check in the handler is deliberate
    defense-in-depth for the same property, not the primary mechanism.
    """
    from lib import dynamo_store

    _setup_aws()
    dynamo_store.put_document("user-a", "doc-1", {
        "title": "x", "document_type": "other", "status": "uploaded",
        "s3_key": "users/user-a/documents/doc-1/x.pdf", "content_type": "application/pdf",
    })

    from handlers import process
    resp = process.handler(_auth_event("user-b", "doc-1"), None)
    assert resp["statusCode"] == 404
