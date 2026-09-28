import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws


def _create_table():
    os.environ["LIFELINE_TABLE"] = "lifeline-localauth-handler-test"
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="lifeline-localauth-handler-test",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _event(body: dict) -> dict:
    return {"body": json.dumps(body)}


@mock_aws
def test_signup_then_login_end_to_end(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    _create_table()
    from handlers import local_auth
    from lib.auth_utils import get_user_id

    signup_resp = local_auth.signup_handler(_event({"email": "demo@example.com", "password": "correct-horse-1"}), None)
    assert signup_resp["statusCode"] == 201
    signup_body = json.loads(signup_resp["body"])
    assert signup_body["email"] == "demo@example.com"
    assert signup_body["id_token"]

    login_resp = local_auth.login_handler(_event({"email": "demo@example.com", "password": "correct-horse-1"}), None)
    assert login_resp["statusCode"] == 200
    login_body = json.loads(login_resp["body"])
    assert login_body["user_id"] == signup_body["user_id"]

    # The issued token must actually authenticate a normal API request.
    fake_api_event = {"requestContext": {}, "headers": {"Authorization": f"Bearer {login_body['id_token']}"}}
    assert get_user_id(fake_api_event) == signup_body["user_id"]


@mock_aws
def test_signup_duplicate_email_returns_400(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    _create_table()
    from handlers import local_auth

    local_auth.signup_handler(_event({"email": "demo@example.com", "password": "correct-horse-1"}), None)
    resp = local_auth.signup_handler(_event({"email": "demo@example.com", "password": "another-pw-123"}), None)
    assert resp["statusCode"] == 400


@mock_aws
def test_login_wrong_password_returns_401(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    _create_table()
    from handlers import local_auth

    local_auth.signup_handler(_event({"email": "demo@example.com", "password": "correct-horse-1"}), None)
    resp = local_auth.login_handler(_event({"email": "demo@example.com", "password": "wrong-password"}), None)
    assert resp["statusCode"] == 401


def test_signup_invalid_body_returns_400(monkeypatch):
    monkeypatch.setenv("LIFELINE_LOCAL_JWT_SECRET", "test-secret")
    from handlers import local_auth

    resp = local_auth.signup_handler({"body": "not json"}, None)
    assert resp["statusCode"] == 400
