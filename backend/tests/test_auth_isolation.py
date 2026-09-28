import sys, os
import pytest
import boto3

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["LIFELINE_DOCS_BUCKET"] = "lifeline-test-bucket"

from moto import mock_aws

from lib.auth_utils import get_user_id, UnauthorizedError
from lib import s3_store


def test_get_user_id_extracts_sub_from_jwt_claims():
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-abc-123"}}}}}
    assert get_user_id(event) == "user-abc-123"


def test_get_user_id_raises_when_missing():
    with pytest.raises(UnauthorizedError):
        get_user_id({"requestContext": {}})


def test_get_user_id_raises_when_sub_empty():
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": ""}}}}}
    with pytest.raises(UnauthorizedError):
        get_user_id(event)


def test_get_user_id_falls_back_to_local_jwt_bearer_token(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    from lib import local_jwt
    token = local_jwt.issue_token("local-user-1", "person@example.com")

    event = {"requestContext": {}, "headers": {"Authorization": f"Bearer {token}"}}
    assert get_user_id(event) == "local-user-1"


def test_get_user_id_local_jwt_fallback_is_case_insensitive_header(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    from lib import local_jwt
    token = local_jwt.issue_token("local-user-2", "person@example.com")

    event = {"requestContext": {}, "headers": {"authorization": f"Bearer {token}"}}
    assert get_user_id(event) == "local-user-2"


def test_get_user_id_rejects_invalid_local_jwt(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    event = {"requestContext": {}, "headers": {"Authorization": "Bearer not-a-real-token"}}
    with pytest.raises(UnauthorizedError):
        get_user_id(event)


def test_get_user_id_rejects_local_jwt_signed_with_wrong_secret(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "secret-a")
    from lib import local_jwt
    token = local_jwt.issue_token("local-user-3", "person@example.com")

    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "secret-b")
    event = {"requestContext": {}, "headers": {"Authorization": f"Bearer {token}"}}
    with pytest.raises(UnauthorizedError):
        get_user_id(event)


def test_get_user_id_prefers_cognito_claims_over_bearer_token(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    from lib import local_jwt
    token = local_jwt.issue_token("local-user-should-not-be-used", "person@example.com")

    event = {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "cognito-user"}}}},
        "headers": {"Authorization": f"Bearer {token}"},
    }
    assert get_user_id(event) == "cognito-user"


def test_s3_key_is_scoped_per_user():
    key_a = s3_store.object_key("user-a", "doc-1", "policy.pdf")
    key_b = s3_store.object_key("user-b", "doc-1", "policy.pdf")
    assert key_a != key_b
    assert key_a.startswith("users/user-a/")
    assert key_b.startswith("users/user-b/")


def test_key_belongs_to_user_rejects_other_users_prefix():
    key = s3_store.object_key("user-a", "doc-1", "id.png")
    assert s3_store.key_belongs_to_user(key, "user-a") is True
    assert s3_store.key_belongs_to_user(key, "user-b") is False


@mock_aws
def test_dynamo_list_documents_never_returns_other_users_items():
    from lib import dynamo_store

    os.environ["LIFELINE_TABLE"] = "lifeline-test"  # set inside the test: dynamo_store reads it per-call
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="lifeline-test",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    dynamo_store.put_document("user-a", "doc-1", {"title": "A's insurance", "document_type": "insurance"})
    dynamo_store.put_document("user-b", "doc-2", {"title": "B's warranty", "document_type": "warranty"})

    a_docs = dynamo_store.list_documents("user-a")
    b_docs = dynamo_store.list_documents("user-b")

    assert len(a_docs) == 1 and a_docs[0]["document_id"] == "doc-1"
    assert len(b_docs) == 1 and b_docs[0]["document_id"] == "doc-2"
    assert all(d["user_id"] == "user-a" for d in a_docs)
