"""
Local OCR via Tesseract.

Only used when LIFELINE_AI_PROVIDER=local (see lib/ai_provider.py and
lib/local_reasoning.py) — the offline, no-AWS-account replacement for
Bedrock's multimodal image understanding when running in GitHub
Codespaces / SAM-local + LocalStack. Requires the `tesseract-ocr`
system package (installed via the devcontainer's postCreateCommand —
see .devcontainer/devcontainer.json) and the `pytesseract` + `Pillow`
Python packages (backend/requirements.txt).

Never used when LIFELINE_AI_PROVIDER=bedrock (the real-AWS path),
so a real Lambda deployment has no dependency on the tesseract binary
being present.
"""
from __future__ import annotations

import io


class OcrError(Exception):
    pass


def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Run Tesseract OCR on raw image bytes and return the recognized
    text. Raises OcrError on anything that stops OCR from running at
    all (corrupt image, missing tesseract binary) — callers treat that
    the same way pdf_extract.PdfExtractionError is treated: an honest
    "failed" status, never a fabricated result. Low/no text recognized
    from a valid image is NOT an error — it's returned as-is (possibly
    empty) and the caller's confidence scoring handles that case.
    """
    try:
        from PIL import Image
        import pytesseract
    except ImportError as e:  # pragma: no cover - packaging issue, not a runtime path
        raise OcrError(f"OCR dependencies not available: {e}") from e

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as e:  # noqa: BLE001
        raise OcrError(f"Could not open image: {e}") from e

    try:
        text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as e:
        raise OcrError(
            "Tesseract OCR is not installed in this environment. "
            "In Codespaces this is installed automatically by "
            ".devcontainer/devcontainer.json's postCreateCommand — "
            "try rebuilding the container."
        ) from e
    except Exception as e:  # noqa: BLE001
        raise OcrError(f"OCR failed: {e}") from e

    return (text or "").strip()
