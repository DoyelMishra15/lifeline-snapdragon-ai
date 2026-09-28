import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from moto import mock_aws


def _create_table():
    os.environ["LIFELINE_TABLE"] = "lifeline-authstore-test"
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="lifeline-authstore-test",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@mock_aws
def test_signup_then_authenticate_succeeds():
    from lib import local_auth_store

    _create_table()
    user_id = local_auth_store.signup("person@example.com", "correct-horse-battery")
    assert user_id
    authenticated_id = local_auth_store.authenticate("person@example.com", "correct-horse-battery")
    assert authenticated_id == user_id


@mock_aws
def test_authenticate_wrong_password_fails():
    from lib import local_auth_store

    _create_table()
    local_auth_store.signup("person@example.com", "correct-horse-battery")
    with pytest.raises(local_auth_store.AuthError):
        local_auth_store.authenticate("person@example.com", "wrong-password")


@mock_aws
def test_authenticate_unknown_email_fails_with_generic_message():
    from lib import local_auth_store

    _create_table()
    with pytest.raises(local_auth_store.AuthError) as exc_info:
        local_auth_store.authenticate("nobody@example.com", "whatever12345")
    # Never reveal whether the email exists.
    assert "incorrect email or password" in str(exc_info.value).lower()


@mock_aws
def test_signup_duplicate_email_fails():
    from lib import local_auth_store

    _create_table()
    local_auth_store.signup("person@example.com", "correct-horse-battery")
    with pytest.raises(local_auth_store.AuthError):
        local_auth_store.signup("person@example.com", "another-password-123")


@mock_aws
def test_signup_is_case_insensitive_on_email():
    from lib import local_auth_store

    _create_table()
    local_auth_store.signup("Person@Example.com", "correct-horse-battery")
    with pytest.raises(local_auth_store.AuthError):
        local_auth_store.signup("person@example.com", "different-password")

    user_id = local_auth_store.authenticate("PERSON@EXAMPLE.COM", "correct-horse-battery")
    assert user_id


def test_signup_rejects_invalid_email():
    from lib import local_auth_store

    with pytest.raises(local_auth_store.AuthError):
        local_auth_store.signup("not-an-email", "correct-horse-battery")


def test_signup_rejects_short_password():
    from lib import local_auth_store

    with pytest.raises(local_auth_store.AuthError):
        local_auth_store.signup("person@example.com", "short")


@mock_aws
def test_password_hash_is_never_stored_in_plaintext():
    from lib import local_auth_store, dynamo_store

    _create_table()
    local_auth_store.signup("person@example.com", "correct-horse-battery")
    item = dynamo_store._table().get_item(
        Key={"PK": "AUTHUSER#person@example.com", "SK": "CREDENTIALS"}
    )["Item"]
    assert "correct-horse-battery" not in item["password_hash"]
    assert item["password_hash"].startswith("pbkdf2_sha256$")


def test_password_hashing_uses_random_salt_each_time():
    from lib import local_auth_store

    h1 = local_auth_store._hash_password("same-password-123")
    h2 = local_auth_store._hash_password("same-password-123")
    assert h1 != h2  # different salts
    assert local_auth_store._verify_password("same-password-123", h1)
    assert local_auth_store._verify_password("same-password-123", h2)


def test_verify_password_rejects_garbage_stored_value():
    from lib import local_auth_store

    assert local_auth_store._verify_password("anything", "not-a-valid-hash-format") is False
