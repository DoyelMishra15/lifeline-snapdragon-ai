"""
Local JWT issuing/verification for LOCAL_MODE auth.

In real AWS, API Gateway's Cognito JWT authorizer verifies the token
and injects its claims into `event.requestContext.authorizer.jwt.claims`
before a Lambda ever runs (see lib/auth_utils.py). `sam local
start-api` does not run a Cognito authorizer at all, so for local dev
each Lambda verifies a token issued by handlers/local_auth.py itself,
signed with a secret shared only between that function and
lib/auth_utils.py's fallback path (LIFELINE_LOCAL_JWT_SECRET, set in
infrastructure/env.local.json — never used, and not present, in a real
`sam deploy`).

The resulting token carries the same `sub` (and `email`) claim shape a
Cognito ID token would, so the rest of the application never needs to
know which one it's looking at.
"""
from __future__ import annotations

import os
import time

import jwt

ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 hours — long enough for a demo session


def _secret() -> str:
    secret = os.environ.get("LIFELINE_LOCAL_JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "LIFELINE_LOCAL_JWT_SECRET is not set — local auth cannot issue or verify "
            "tokens without it. It is set automatically by infrastructure/env.local.json "
            "when running via ./start.sh; if you're invoking SAM directly, pass "
            "--env-vars infrastructure/env.local.json."
        )
    return secret


def issue_token(user_id: str, email: str) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "email": email, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Returns the decoded claims dict. Raises jwt.PyJWTError on any invalid/expired token."""
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
