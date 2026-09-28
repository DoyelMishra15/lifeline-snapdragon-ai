"""
POST /auth/signup   body: {"email": "...", "password": "..."}
POST /auth/login    body: {"email": "...", "password": "..."}

LOCAL_MODE-only: these two routes exist so LifeLine has a real,
working sign-up/sign-in flow in GitHub Codespaces / SAM-local +
LocalStack, where Cognito (a LocalStack Pro-only service) isn't
available. Both are marked `Auth: {Authorizer: NONE}` in
infrastructure/template.yaml (obviously — you can't authenticate with
a token you don't have yet), same as Cognito's own hosted sign-up/
sign-in pages are unauthenticated.

Real AWS deployments keep using Cognito exactly as before (see
frontend/src/amplifyConfig.js switching on whether Cognito env vars
are set) — the frontend never calls these routes unless
VITE_LOCAL_MODE is set. These routes shipping alongside a real
Cognito-protected API is harmless (they only ever create/authenticate
local-only user records under their own DynamoDB namespace — see
lib/local_auth_store.py) but only makes sense as part of the local
dev workflow; do not point a real production frontend at them.

On success, both return {"user_id", "email", "id_token"} — the token
is a local JWT (lib/local_jwt.py) with the same `sub`/`email` claim
shape a Cognito ID token has, verified by lib/auth_utils.py's fallback
path on every subsequent authenticated request.
"""
from __future__ import annotations

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import local_auth_store, local_jwt
from lib.http import response, error, parse_body


def signup_handler(event, context):
    try:
        body = parse_body(event)
    except Exception:
        return error(400, "Invalid JSON body")

    email, password = body.get("email", ""), body.get("password", "")
    try:
        user_id = local_auth_store.signup(email, password)
    except local_auth_store.AuthError as e:
        return error(400, str(e))

    token = local_jwt.issue_token(user_id, email.strip().lower())
    return response(201, {"user_id": user_id, "email": email.strip().lower(), "id_token": token})


def login_handler(event, context):
    try:
        body = parse_body(event)
    except Exception:
        return error(400, "Invalid JSON body")

    email, password = body.get("email", ""), body.get("password", "")
    try:
        user_id = local_auth_store.authenticate(email, password)
    except local_auth_store.AuthError as e:
        return error(401, str(e))

    token = local_jwt.issue_token(user_id, email.strip().lower())
    return response(200, {"user_id": user_id, "email": email.strip().lower(), "id_token": token})
