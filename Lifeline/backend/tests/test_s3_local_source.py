import base64
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws

BUCKET_NAME = "lifeline-source-test-bucket"


def _setup_bucket():
    os.environ["LIFELINE_DOCS_BUCKET"] = BUCKET_NAME
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET_NAME)
    return s3


@mock_aws
def test_local_mode_returns_data_uri(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_MODE", "true")
    from lib import s3_store

    s3 = _setup_bucket()
    key = s3_store.object_key("user-a", "doc-1", "policy.pdf")
    content = b"%PDF-1.4 fake pdf bytes"
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=content, ContentType="application/pdf")

    source = s3_store.get_document_source(key, "user-a")
    assert source.startswith("data:application/pdf;base64,")
    encoded = source.split(",", 1)[1]
    assert base64.b64decode(encoded) == content


@mock_aws
def test_local_mode_returns_none_for_wrong_user(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_MODE", "true")
    from lib import s3_store

    _setup_bucket()
    key = s3_store.object_key("user-a", "doc-1", "policy.pdf")
    assert s3_store.get_document_source(key, "user-b") is None


@mock_aws
def test_non_local_mode_returns_presigned_url(monkeypatch):
    monkeypatch.delenv("LIFELINE_LOCAL_MODE", raising=False)
    from lib import s3_store

    s3 = _setup_bucket()
    key = s3_store.object_key("user-a", "doc-1", "policy.pdf")
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=b"content", ContentType="application/pdf")

    source = s3_store.get_document_source(key, "user-a")
    assert source is not None
    assert source.startswith("http")
    assert not source.startswith("data:")


@mock_aws
def test_local_mode_missing_object_returns_none(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_MODE", "true")
    from lib import s3_store

    _setup_bucket()
    key = s3_store.object_key("user-a", "doc-missing", "gone.pdf")
    assert s3_store.get_document_source(key, "user-a") is None
