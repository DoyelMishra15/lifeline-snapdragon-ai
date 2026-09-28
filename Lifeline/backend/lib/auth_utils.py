"""
Auth helper.

In real AWS, we do NOT verify JWTs by hand in Lambda code. API Gateway
is configured with a Cognito authorizer (see
infrastructure/template.yaml), which rejects unauthenticated requests
before they ever reach Lambda and injects the verified claims into the
request context — get_user_id() just reads that already-verified
identity out of the event.

`sam local start-api` (used for the Codespaces/LocalStack workflow —
see infrastructure/env.local.json and lib/local_jwt.py) does not run a
Cognito authorizer at all, so when those claims are absent, get_user_id()
falls back to reading and verifying an `Authorization: Bearer <token>`
header directly, using the same local JWT handlers/local_auth.py
issues. This fallback is unreachable in a real deployment: with
Cognito as the HttpApi's DefaultAuthorizer, an unauthenticated request
is rejected by API Gateway itself and never reaches Lambda at all, so
Lambda never sees a request with both no Cognito claims AND a route
that isn't explicitly public.
"""
from __future__ import annotations


class UnauthorizedError(Exception):
    pass


def get_user_id(event: dict) -> str:
    """
    Return the caller's stable user id ("sub"). Tries the Cognito
    claims API Gateway injects first (real AWS); falls back to
    verifying a local JWT from the Authorization header (SAM local +
    LocalStack). Raises UnauthorizedError if neither is present/valid,
    which handlers turn into a 401.
    """
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        sub = claims["sub"]
        if sub:
            return sub
    except (KeyError, TypeError):
        pass

    token = _extract_bearer_token(event)
    if token:
        try:
            from lib import local_jwt
            claims = local_jwt.verify_token(token)
            sub = claims.get("sub")
            if sub:
                return sub
        except Exception:  # noqa: BLE001 - any JWT error (expired, bad signature, etc) -> unauthorized
            pass

    raise UnauthorizedError("Missing or invalid authentication context")


def _extract_bearer_token(event: dict) -> str | None:
    headers = event.get("headers") or {}
    # API Gateway/SAM local may lower-case header names.
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return auth_header[len("Bearer "):].strip() or None
