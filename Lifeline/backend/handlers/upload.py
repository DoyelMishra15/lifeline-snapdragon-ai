"""
POST /documents/upload-url

Body: {"filename": "policy.pdf", "content_type": "application/pdf", "size_bytes": 123456}
  or, in LOCAL_MODE, additionally: {"file_content_base64": "..."}

Two upload flows, both producing an identical DynamoDB record and API
response shape (`document_id`, `upload_url`, `s3_key`):

- Real AWS (no `file_content_base64` in the body): returns a presigned
  S3 PUT URL scoped to this user's prefix. The frontend PUTs the file
  directly to S3 — file bytes never pass through this Lambda — then
  calls POST /documents/{document_id}/process to kick off extraction.
- LOCAL_MODE (frontend sends `file_content_base64`, since a presigned
  URL generated inside a SAM-local container isn't reachable from the
  browser — see lib/s3_store.store_uploaded_file_locally): the file is
  decoded and written to S3 (LocalStack) directly from this Lambda.
  `upload_url` is returned as null and the frontend skips the PUT step
  entirely before calling .../process.
"""
from __future__ import annotations

import base64
import binascii
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import s3_store, dynamo_store
from lib.auth_utils import get_user_id, UnauthorizedError
from lib.http import response, error, parse_body


def handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))

    try:
        body = parse_body(event)
    except Exception:
        return error(400, "Invalid JSON body")

    filename = body.get("filename")
    content_type = body.get("content_type")
    size_bytes = body.get("size_bytes")
    file_content_base64 = body.get("file_content_base64")

    if not filename or not content_type:
        return error(400, "filename and content_type are required")

    if file_content_base64:
        return _handle_local_inline_upload(user_id, filename, content_type, file_content_base64)

    valid, msg = s3_store.validate_upload_request(content_type, size_bytes)
    if not valid:
        return error(400, msg)

    presigned = s3_store.create_presigned_upload(user_id, filename, content_type)

    dynamo_store.put_document(
        user_id,
        presigned["document_id"],
        {
            "filename": filename,
            "content_type": content_type,
            "s3_key": presigned["key"],
            "status": "uploaded",
            "title": filename,
            "document_type": "other",
        },
    )

    return response(201, {
        "document_id": presigned["document_id"],
        "upload_url": presigned["upload_url"],
        "s3_key": presigned["key"],
    })


def _handle_local_inline_upload(user_id: str, filename: str, content_type: str, file_content_base64: str) -> dict:
    try:
        content_bytes = base64.b64decode(file_content_base64, validate=True)
    except (binascii.Error, ValueError):
        return error(400, "file_content_base64 is not valid base64")

    valid, msg = s3_store.validate_upload_request(content_type, len(content_bytes))
    if not valid:
        return error(400, msg)
    if len(content_bytes) > s3_store.LOCAL_MAX_FILE_SIZE_BYTES:
        return error(400, f"File exceeds the {s3_store.LOCAL_MAX_FILE_SIZE_BYTES // (1024*1024)}MB "
                           f"limit for local uploads (inline base64 payload)")

    stored = s3_store.store_uploaded_file_locally(user_id, filename, content_type, content_bytes)

    dynamo_store.put_document(
        user_id,
        stored["document_id"],
        {
            "filename": filename,
            "content_type": content_type,
            "s3_key": stored["key"],
            "status": "uploaded",
            "title": filename,
            "document_type": "other",
        },
    )

    return response(201, {"document_id": stored["document_id"], "upload_url": None, "s3_key": stored["key"]})
