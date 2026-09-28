"""
Local auth user store — the LOCAL_MODE replacement for Amazon Cognito.

LocalStack's free/community edition does not include Cognito (it's a
Pro-only service), so running LifeLine entirely offline in GitHub
Codespaces needs a different way to authenticate users. This module
implements real signup/login against the SAME DynamoDB table LifeLine
already uses (LocalStack-backed locally, real DynamoDB in production),
under its own PK namespace so it never collides with application data:

    PK = AUTHUSER#<email lowercased>   SK = CREDENTIALS

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib `hashlib`, no
extra dependency) and a random salt — never stored or logged in
plaintext. This is a real, working local auth system, not a stub: it
is only ever wired up via backend/handlers/local_auth.py, which is
itself only meaningful when LIFELINE_LOCAL_MODE=true (see
infrastructure/env.local.json) — a real `sam deploy` to AWS keeps
using Cognito exactly as before, unchanged.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid

from lib import dynamo_store

_PBKDF2_ITERATIONS = 260_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Raised for any signup/login failure with a user-safe message."""


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return secrets.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def _key(email: str) -> tuple[str, str]:
    return f"AUTHUSER#{email.strip().lower()}", "CREDENTIALS"


def validate_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


def validate_password(password: str) -> tuple[bool, str | None]:
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters."
    return True, None


def signup(email: str, password: str) -> str:
    """
    Creates a new local user. Returns the new user's id (used as the
    JWT `sub`, exactly like a Cognito `sub`). Raises AuthError if the
    email is already registered or the input is invalid.
    """
    if not validate_email(email):
        raise AuthError("Enter a valid email address.")
    ok, msg = validate_password(password)
    if not ok:
        raise AuthError(msg)

    pk, sk = _key(email)
    table = dynamo_store._table()
    existing = table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
    if existing:
        raise AuthError("An account with this email already exists.")

    user_id = str(uuid.uuid4())
    table.put_item(Item={
        "PK": pk,
        "SK": sk,
        "user_id": user_id,
        "email": email.strip().lower(),
        "password_hash": _hash_password(password),
        "created_at": dynamo_store._now(),
    })
    return user_id


def authenticate(email: str, password: str) -> str:
    """
    Verifies email/password. Returns the user's id on success. Raises
    AuthError (with a deliberately generic message — never reveals
    whether the email exists) on any failure.
    """
    pk, sk = _key(email)
    table = dynamo_store._table()
    item = table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
    if not item or not _verify_password(password, item.get("password_hash", "")):
        raise AuthError("Incorrect email or password.")
    return item["user_id"]
