"""
PDF text extraction.

Handles text-layer PDFs (the common case for insurance policies,
bills, certificates exported from a word processor or downloaded from
a provider portal). Scanned/image-only PDFs have no text layer to
extract — pdf_has_usable_text() distinguishes that case so the caller
can fail honestly (needs_review with a clear explanation) instead of
sending Bedrock a blank or fabricated document.

OCR of scanned PDFs is out of scope for the MVP — see
docs/limitations.md. A photo of the same document (PNG/JPEG) works
today via Bedrock's multimodal input in bedrock_client.py.
"""
from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MIN_USABLE_CHARS = 40  # below this, treat as "no usable text layer"
MAX_CHARS_SENT_TO_MODEL = 15000
MAX_PAGES = 20


class PdfExtractionError(Exception):
    pass


def extract_text(pdf_bytes: bytes) -> str:
    """
    Extract text from a PDF's text layer. Raises PdfExtractionError on
    a corrupt/unreadable/encrypted file — callers must catch this and
    fail gracefully rather than let it propagate as a 500.
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except PdfReadError as e:
        raise PdfExtractionError(f"Could not open PDF: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise PdfExtractionError(f"Unexpected error opening PDF: {e}") from e

    if reader.is_encrypted:
        # Try an empty password (some "encrypted" PDFs just have owner
        # restrictions with no open password); if that fails, give up
        # honestly rather than guessing.
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise PdfExtractionError(f"PDF is password-protected: {e}") from e

    chunks = []
    for i, page in enumerate(reader.pages):
        if i >= MAX_PAGES:
            break
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a single bad page shouldn't kill extraction
            continue

    text = "\n".join(chunks).strip()
    return text[:MAX_CHARS_SENT_TO_MODEL]


def has_usable_text(text: str) -> bool:
    return len(text.strip()) >= MIN_USABLE_CHARS
