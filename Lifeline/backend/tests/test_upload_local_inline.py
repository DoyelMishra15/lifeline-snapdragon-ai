import base64
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws

TABLE_NAME = "lifeline-upload-local-test"
BUCKET_NAME = "lifeline-upload-local-test-bucket"


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


def _auth_event(user_id, body):
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}},
        "body": json.dumps(body),
    }


@mock_aws
def test_local_inline_upload_stores_file_and_skips_presigned_url():
    from handlers import upload
    from lib import dynamo_store, s3_store

    s3 = _setup_aws()
    content = b"%PDF-1.4 fake pdf content for testing"
    body = {
        "filename": "policy.pdf",
        "content_type": "application/pdf",
        "file_content_base64": base64.b64encode(content).decode("ascii"),
    }
    resp = upload.handler(_auth_event("user-a", body), None)
    assert resp["statusCode"] == 201
    result = json.loads(resp["body"])
    assert result["upload_url"] is None
    assert result["document_id"]

    doc = dynamo_store.get_document("user-a", result["document_id"])
    assert doc["status"] == "uploaded"
    assert doc["s3_key"] == result["s3_key"]

    stored_bytes = s3_store.get_object_bytes(doc["s3_key"])
    assert stored_bytes == content


@mock_aws
def test_local_inline_upload_rejects_bad_base64():
    from handlers import upload

    _setup_aws()
    body = {"filename": "x.pdf", "content_type": "application/pdf", "file_content_base64": "not-valid-base64!!!"}
    resp = upload.handler(_auth_event("user-a", body), None)
    assert resp["statusCode"] == 400


@mock_aws
def test_local_inline_upload_rejects_oversized_file():
    from handlers import upload
    from lib import s3_store

    _setup_aws()
    oversized = b"a" * (s3_store.LOCAL_MAX_FILE_SIZE_BYTES + 1)
    body = {
        "filename": "big.pdf", "content_type": "application/pdf",
        "file_content_base64": base64.b64encode(oversized).decode("ascii"),
    }
    resp = upload.handler(_auth_event("user-a", body), None)
    assert resp["statusCode"] == 400


@mock_aws
def test_local_inline_upload_rejects_disallowed_content_type():
    from handlers import upload

    _setup_aws()
    body = {
        "filename": "x.exe", "content_type": "application/x-msdownload",
        "file_content_base64": base64.b64encode(b"whatever").decode("ascii"),
    }
    resp = upload.handler(_auth_event("user-a", body), None)
    assert resp["statusCode"] == 400


@mock_aws
def test_real_aws_flow_unaffected_when_no_inline_content_given():
    from handlers import upload

    _setup_aws()
    body = {"filename": "policy.pdf", "content_type": "application/pdf", "size_bytes": 1000}
    resp = upload.handler(_auth_event("user-a", body), None)
    assert resp["statusCode"] == 201
    result = json.loads(resp["body"])
    assert result["upload_url"] is not None  # real presigned-URL path still works unchanged
