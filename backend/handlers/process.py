"""
POST /documents/{document_id}/process

Triggered by the frontend right after a successful S3 PUT (simplest
reliable approach for the hackathon timeline — an S3 ObjectCreated
event + Lambda trigger is the natural production upgrade, and Step
Functions could orchestrate extract -> validate -> store as its own
state machine; for the MVP that orchestration is done inline here to
keep the moving parts demoable within the hackathon window).

Flow: S3 (read bytes) -> Bedrock (extract) -> validate (schema.py)
      -> DynamoDB (store) -> EventBridge event (attention sweep will
      pick it up on its next scheduled run).

Fails gracefully: if Bedrock errors or returns something that doesn't
pass validation, the document is marked failed/needs_review (never
silently dropped, never a fabricated fallback), and the endpoint
still returns 200 with a status the UI can show + retry.
"""
from __future__ import annotations

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import s3_store, dynamo_store, ai_provider, pdf_extract
from lib.schema import parse_and_validate
from lib.auth_utils import get_user_id, UnauthorizedError
from lib.http import response, error

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def handler(event, context):
    try:
        user_id = get_user_id(event)
    except UnauthorizedError as e:
        return error(401, str(e))

    document_id = (event.get("pathParameters") or {}).get("document_id")
    if not document_id:
        return error(400, "document_id is required in path")

    doc = dynamo_store.get_document(user_id, document_id)
    if not doc:
        return error(404, "Document not found")
    if doc["user_id"] != user_id:
        return error(403, "Forbidden")

    dynamo_store.update_document_status(user_id, document_id, "processing")

    try:
        file_bytes = s3_store.get_object_bytes(doc["s3_key"])
    except Exception as e:  # noqa: BLE001
        dynamo_store.update_document_status(
            user_id, document_id, "failed", {"error_message": f"Could not read uploaded file: {e}"}
        )
        return response(200, {"document_id": document_id, "status": "failed",
                               "error": "Could not read uploaded file. You can retry."})

    content_type = doc.get("content_type", "")

    if content_type in IMAGE_TYPES:
        extraction = ai_provider.extract_document(image_bytes=file_bytes, image_media_type=content_type)

    elif content_type == "application/pdf":
        try:
            pdf_text = pdf_extract.extract_text(file_bytes)
        except pdf_extract.PdfExtractionError as e:
            dynamo_store.update_document_status(
                user_id, document_id, "failed", {"error_message": str(e)}
            )
            return response(200, {"document_id": document_id, "status": "failed",
                                   "error": str(e), "retryable": False})

        if not pdf_extract.has_usable_text(pdf_text):
            # Honest failure rather than sending Bedrock a near-empty or
            # fabricated document: scanned/image-only PDFs have no text
            # layer to extract in this MVP (see docs/limitations.md).
            # A photo of the same document works via the image path above.
            dynamo_store.update_document_status(
                user_id, document_id, "needs_review",
                {"error_message": "This PDF has no extractable text layer (likely a scanned image). "
                                   "Try uploading a photo of the document instead."},
            )
            return response(200, {
                "document_id": document_id, "status": "needs_review",
                "error": "No extractable text found in this PDF — it may be a scanned image. "
                         "Try uploading a photo (PNG/JPEG) of the document instead.",
            })

        extraction = ai_provider.extract_document(text=pdf_text)

    else:
        dynamo_store.update_document_status(
            user_id, document_id, "failed",
            {"error_message": f"Unsupported content type for extraction: {content_type}"},
        )
        return response(200, {"document_id": document_id, "status": "failed",
                               "error": f"Unsupported content type: {content_type}", "retryable": False})

    if not extraction.get("ok"):
        status = "failed"
        dynamo_store.update_document_status(
            user_id, document_id, status, {"error_message": extraction.get("error", "Unknown Bedrock error")}
        )
        return response(200, {"document_id": document_id, "status": status,
                               "error": extraction.get("error"),
                               "retryable": extraction.get("retryable", True)})

    result = parse_and_validate(extraction["text"])
    if not result.ok:
        dynamo_store.update_document_status(
            user_id, document_id, "needs_review",
            {"error_message": f"Extraction did not pass validation: {result.error}",
             "raw_model_output": (result.raw_text or "")[:2000]},
        )
        return response(200, {"document_id": document_id, "status": "needs_review",
                               "error": result.error})

    extracted = result.document.model_dump()
    dynamo_store.update_document_status(
        user_id, document_id, "processed",
        {
            "document_type": extracted["document_type"],
            "title": extracted["title"],
            "provider": extracted.get("provider"),
            "expiry_date": extracted.get("expiry_date"),
            "important_dates": extracted.get("important_dates", []),
            "amount": extracted.get("amount"),
            "actions": extracted.get("actions", []),
            "relevant_entities": extracted.get("relevant_entities", []),
            "warnings": extracted.get("warnings", []),
            "confidence": extracted.get("confidence"),
        },
    )

    if extracted.get("expiry_date"):
        dynamo_store.put_event(user_id, document_id, extracted["expiry_date"], {
            "event_type": "expiry",
            "document_id": document_id,
            "title": extracted["title"],
        })

    return response(200, {"document_id": document_id, "status": "processed", "extraction": extracted})
