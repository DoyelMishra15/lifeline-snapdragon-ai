import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import local_reasoning


def _extracted(text):
    result = local_reasoning.extract_document(text=text)
    assert result["ok"] is True
    return json.loads(result["text"])


def test_extracts_insurance_policy_with_expiry_and_amount():
    text = """
    Health Insurance Policy
    Provider: Acme Insurance
    Policy Number: 12345
    Premium: $450.00
    This policy expires on 2026-10-14.
    """
    doc = _extracted(text)
    assert doc["document_type"] == "insurance"
    assert doc["provider"] == "Acme Insurance"
    assert doc["expiry_date"] == "2026-10-14"
    assert doc["amount"] == "$450.00" or doc["amount"] == "$450.0"
    assert doc["confidence"] > 0.7
    assert "Renew before expiry" in doc["actions"]


def test_extracts_date_in_month_name_format():
    text = "Warranty Card\nIssued by: Acme Electronics Inc.\nThis warranty is valid until October 14, 2026."
    doc = _extracted(text)
    assert doc["document_type"] == "warranty"
    assert doc["expiry_date"] == "2026-10-14"


def test_extracts_day_month_year_format():
    text = "Certificate\nThis certifies completion.\nValid until 14 October 2026."
    doc = _extracted(text)
    assert doc["expiry_date"] == "2026-10-14"


def test_extracts_slash_date_day_first():
    text = "Bill\nAmount due: $99.00\nPayment due date: 14/10/2026"
    doc = _extracted(text)
    assert doc["document_type"] == "bill"
    assert doc["expiry_date"] == "2026-10-14"
    assert "Pay before the due date" in doc["actions"]


def test_very_short_text_gets_low_confidence_and_warning():
    doc = _extracted("hi")
    assert doc["confidence"] <= 0.3
    assert doc["warnings"]
    assert doc["document_type"] == "other"


def test_no_expiry_date_found_adds_warning_for_expiry_bearing_types():
    text = "Insurance Policy\nProvider: Acme Insurance\nThis is a general description with no dates at all here."
    doc = _extracted(text)
    assert doc["document_type"] == "insurance"
    assert doc["expiry_date"] is None
    assert any("date" in w.lower() for w in doc["warnings"])


def test_never_fabricates_provider_when_absent():
    text = "Random document with some text but no company name suffix anywhere in it at all today."
    doc = _extracted(text)
    assert doc["provider"] is None


def test_confidence_is_always_in_valid_range():
    for text in ["short", "A" * 500, "Insurance Policy Provider: X Corp expires 2026-01-01 $100"]:
        doc = _extracted(text)
        assert 0.0 <= doc["confidence"] <= 1.0


def test_result_always_passes_schema_validation():
    from lib.schema import parse_and_validate

    texts = [
        "hi",
        "",
        "Health Insurance Policy\nProvider: Acme\nExpires 2026-10-14\n$100",
        "Random text " * 50,
    ]
    for text in texts:
        result = local_reasoning.extract_document(text=text)
        validated = parse_and_validate(result["text"])
        assert validated.ok is True, validated.error


def test_extract_document_ocr_failure_returns_not_ok(monkeypatch):
    from lib import ocr

    def fail(_bytes):
        raise ocr.OcrError("tesseract not found")

    monkeypatch.setattr("lib.local_reasoning.ocr.extract_text_from_image", fail)
    result = local_reasoning.extract_document(image_bytes=b"fake-image-bytes")
    assert result["ok"] is False
    assert "tesseract" in result["error"].lower()


def test_extract_document_from_image_uses_ocr_text(monkeypatch):
    monkeypatch.setattr(
        "lib.local_reasoning.ocr.extract_text_from_image",
        lambda _bytes: "Passport\nNationality: Example\nDate of expiry: 2026-12-01",
    )
    result = local_reasoning.extract_document(image_bytes=b"fake-image-bytes")
    assert result["ok"] is True
    doc = json.loads(result["text"])
    assert doc["document_type"] == "passport"


# ---------------------------------------------------------------
# Emergency plan generation
# ---------------------------------------------------------------

def test_lost_wallet_plan_includes_relevant_documents():
    user_data = {
        "documents": [
            {"document_id": "d1", "document_type": "identity", "title": "ID Card"},
            {"document_id": "d2", "document_type": "bill", "title": "Electric Bill"},
        ],
        "emergency_contact": {"name": "Alex", "phone": "555-1234"},
    }
    result = local_reasoning.draft_emergency_plan(situation="Lost my wallet/documents", user_data=user_data)
    assert result["ok"] is True
    plan = json.loads(result["text"])
    assert plan["relevant_documents"] == ["d1"]  # only the identity doc, not the bill
    assert all(s["source_document_ids"] == ["d1"] for s in plan["steps"])
    assert plan["missing_information"] == []  # emergency contact present, relevant docs present


def test_plan_flags_missing_emergency_contact_and_documents():
    result = local_reasoning.draft_emergency_plan(
        situation="Lost my wallet/documents", user_data={"documents": [], "emergency_contact": None}
    )
    plan = json.loads(result["text"])
    assert "No relevant documents are on file yet for this situation." in plan["missing_information"]
    assert "No emergency contact is saved — add one in Settings." in plan["missing_information"]


def test_unknown_situation_label_falls_back_to_other_template():
    result = local_reasoning.draft_emergency_plan(situation="Something unrecognized", user_data={"documents": []})
    plan = json.loads(result["text"])
    assert plan["summary"] == local_reasoning._PLAN_TEMPLATES["other"]["summary"]


def test_plan_always_carries_the_disclaimer():
    result = local_reasoning.draft_emergency_plan(situation="Travel emergency", user_data={"documents": []})
    plan = json.loads(result["text"])
    assert "does not diagnose" in plan["disclaimer"]


def test_plan_result_is_json_parseable_and_has_required_keys():
    for label in ["Lost my phone", "Hospital / medical emergency", "I'm temporarily unavailable", "Other"]:
        result = local_reasoning.draft_emergency_plan(situation=label, user_data={"documents": []})
        plan = json.loads(result["text"])
        for key in ("situation", "summary", "steps", "relevant_documents", "missing_information", "disclaimer"):
            assert key in plan
