"""
S3 helper for LifeLine source documents.

Objects are always keyed under the owning user's Cognito `sub`, so a
presigned URL scoped to one user can never resolve into another
user's prefix. The bucket itself must be private (no public access) —
see infrastructure/template.yaml.
"""
from __future__ import annotations

import os
import uuid

import boto3
from botocore.config import Config

PRESIGN_EXPIRY_SECONDS = 300

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB — real-AWS presigned-URL upload path
# The LOCAL_MODE direct-upload path (handlers/upload.py) sends the file
# inline as base64 in the request body instead of a presigned PUT, so
# it's bounded well under API Gateway/Lambda's own payload limits
# (6 MB synchronous Lambda payload limit; base64 adds ~33% overhead).
LOCAL_MAX_FILE_SIZE_BYTES = 4 * 1024 * 1024  # 4 MB


def _bucket_name() -> str:
    # Read at call time, not import time — see the matching note on
    # dynamo_store._table(); keeps behavior identical in Lambda but
    # avoids stale-binding surprises across a shared test session.
    return os.environ.get("LIFELINE_DOCS_BUCKET", "lifeline-documents-dev")


def _client():
    # Path-style addressing works against both real S3 and LocalStack
    # (LocalStack's virtual-hosted-style support is inconsistent
    # depending on the bucket name); it's a safe default for both.
    # The endpoint itself (real AWS vs LocalStack) is controlled purely
    # by the AWS_ENDPOINT_URL environment variable, which boto3>=1.28
    # reads automatically — no code branching needed here.
    return boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))


def object_key(user_id: str, document_id: str, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"users/{user_id}/documents/{document_id}/{safe_name}"


def validate_upload_request(content_type: str, size_bytes: int) -> tuple[bool, str | None]:
    if content_type not in ALLOWED_CONTENT_TYPES:
        return False, f"Unsupported content type: {content_type}"
    if size_bytes is not None and size_bytes > MAX_FILE_SIZE_BYTES:
        return False, f"File exceeds {MAX_FILE_SIZE_BYTES // (1024*1024)}MB limit"
    return True, None


def create_presigned_upload(user_id: str, filename: str, content_type: str) -> dict:
    document_id = str(uuid.uuid4())
    key = object_key(user_id, document_id, filename)
    bucket = _bucket_name()
    url = _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
    return {"document_id": document_id, "upload_url": url, "key": key, "bucket": bucket}


def create_presigned_download(key: str) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": key},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )


def get_object_bytes(key: str) -> bytes:
    resp = _client().get_object(Bucket=_bucket_name(), Key=key)
    return resp["Body"].read()


def _is_local_mode() -> bool:
    return os.environ.get("LIFELINE_LOCAL_MODE", "").strip().lower() == "true"


def get_document_source(key: str, user_id: str) -> str | None:
    """
    Returns something the browser can use to view/download the
    original file at `key` — or None if it can't be produced (missing
    object, access error). Used by handlers/documents.py::get_handler.

    Real AWS: a normal presigned GET URL (unchanged behavior).
    LOCAL_MODE: a `data:` URI with the file inlined as base64, fetched
    server-side. A presigned URL generated inside a SAM-local Lambda
    container would embed LocalStack's internal Docker-network
    hostname (e.g. http://localstack:4566), which the browser —
    running outside that network — can never resolve; a data: URI
    sidesteps that entirely and needs no separate download endpoint.
    Kept practical by the existing LOCAL_MAX_FILE_SIZE_BYTES upload
    cap, so this never inlines something unreasonably large.
    """
    if not key_belongs_to_user(key, user_id):
        return None

    if _is_local_mode():
        try:
            resp = _client().get_object(Bucket=_bucket_name(), Key=key)
            content_bytes = resp["Body"].read()
            content_type = resp.get("ContentType") or "application/octet-stream"
        except Exception:
            return None
        import base64
        return f"data:{content_type};base64,{base64.b64encode(content_bytes).decode('ascii')}"

    try:
        return create_presigned_download(key)
    except Exception:
        return None


def put_object_bytes(key: str, content_bytes: bytes, content_type: str) -> None:
    """
    Server-side upload, used only by the LOCAL_MODE direct-upload path
    (see handlers/upload.py). The real-AWS flow never calls this — the
    frontend PUTs straight to a presigned URL instead, so file bytes
    never pass through Lambda.
    """
    _client().put_object(Bucket=_bucket_name(), Key=key, Body=content_bytes, ContentType=content_type)


def store_uploaded_file_locally(user_id: str, filename: str, content_type: str, content_bytes: bytes) -> dict:
    """
    LOCAL_MODE counterpart to create_presigned_upload(): writes the
    file to S3 (LocalStack) directly from the Lambda instead of
    returning a presigned URL for the browser to PUT to.

    Local dev skips presigned URLs entirely because a URL signed
    inside a SAM-local Lambda container embeds LocalStack's internal
    Docker-network hostname (e.g. http://localstack:4566), which the
    browser — running outside that network — can never resolve.
    Writing the object server-side sidesteps that networking problem
    completely.
    """
    document_id = str(uuid.uuid4())
    key = object_key(user_id, document_id, filename)
    put_object_bytes(key, content_bytes, content_type)
    return {"document_id": document_id, "key": key, "bucket": _bucket_name()}


def key_belongs_to_user(key: str, user_id: str) -> bool:
    return key.startswith(f"users/{user_id}/")
