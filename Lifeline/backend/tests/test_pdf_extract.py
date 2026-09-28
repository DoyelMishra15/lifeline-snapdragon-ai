import io
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import pdf_extract

reportlab = pytest.importorskip("reportlab")  # test-only dependency; not required at runtime
from reportlab.pdfgen import canvas  # noqa: E402
from pypdf import PdfWriter  # noqa: E402


def _make_text_pdf(text_lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text_lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def _make_blank_pdf() -> bytes:
    """A structurally valid PDF with a page but no text content at all."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_extracts_real_text_from_a_text_pdf():
    pdf_bytes = _make_text_pdf([
        "Health Insurance Policy",
        "Provider: Acme Insurance",
        "Policy expires: 2026-10-14",
    ])
    text = pdf_extract.extract_text(pdf_bytes)
    assert "Health Insurance Policy" in text
    assert "Acme Insurance" in text
    assert pdf_extract.has_usable_text(text) is True


def test_blank_pdf_has_no_usable_text():
    pdf_bytes = _make_blank_pdf()
    text = pdf_extract.extract_text(pdf_bytes)
    assert pdf_extract.has_usable_text(text) is False


def test_corrupt_pdf_bytes_raise_extraction_error():
    with pytest.raises(pdf_extract.PdfExtractionError):
        pdf_extract.extract_text(b"this is not a pdf at all")


def test_multi_page_text_is_concatenated():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 800, "Page one content")
    c.showPage()
    c.drawString(72, 800, "Page two content")
    c.save()
    text = pdf_extract.extract_text(buf.getvalue())
    assert "Page one content" in text
    assert "Page two content" in text


def test_text_sent_to_model_is_capped():
    long_line = "A" * 50000
    pdf_bytes = _make_text_pdf([long_line])
    text = pdf_extract.extract_text(pdf_bytes)
    assert len(text) <= pdf_extract.MAX_CHARS_SENT_TO_MODEL
