"""
GET  /profile
PUT  /profile   body: {"display_name": "...", "emergency_contact": {"name": "...", "phone": "..."}}
"""
from __future__ import annotations

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import dynamo_store
from lib.auth_utils import get_user_id, UnauthorizedError
from lib.http import response, error, parse_body

ALLOWED_FIELDS = {"display_name", "emergency_contact"}


def get_handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))
    profile = dynamo_store.get_profile(user_id) or {"user_id": user_id}
    return response(200, profile)


def put_handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))
    try:
        body = parse_body(event)
    except Exception:
        return error(400, "Invalid JSON body")

    update = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
    saved = dynamo_store.put_profile(user_id, update)
    return response(200, saved)
