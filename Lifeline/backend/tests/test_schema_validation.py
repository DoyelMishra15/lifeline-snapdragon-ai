import sys, os, json

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib.schema import parse_and_validate


def test_valid_extraction_passes():
    payload = {
        "document_type": "insurance",
        "title": "Health Insurance Policy",
        "provider": "Example Insurance",
        "expiry_date": "2026-10-14",
        "important_dates": [{"date": "2026-10-14", "type": "expiry", "description": "Policy expires"}],
        "actions": ["Renew before expiry"],
        "warnings": [],
        "confidence": 0.93,
    }
    result = parse_and_validate(json.dumps(payload))
    assert result.ok is True
    assert result.document.title == "Health Insurance Policy"
    assert result.document.confidence == 0.93


def test_strips_markdown_code_fences():
    payload = {"document_type": "warranty", "title": "Laptop Warranty", "confidence": 0.8}
    text = "```json\n" + json.dumps(payload) + "\n```"
    result = parse_and_validate(text)
    assert result.ok is True
    assert result.document.document_type == "warranty"


def test_invalid_json_fails_gracefully():
    result = parse_and_validate("not json at all {{{")
    assert result.ok is False
    assert result.error  # some explanatory message, exact wording covered by the fallback tests below


def test_missing_required_field_fails():
    result = parse_and_validate(json.dumps({"title": "Something"}))  # no document_type/confidence
    assert result.ok is False


def test_bad_date_format_fails():
    payload = {"document_type": "bill", "title": "Electric Bill", "expiry_date": "10-14-2026", "confidence": 0.9}
    result = parse_and_validate(json.dumps(payload))
    assert result.ok is False


def test_unknown_document_type_falls_back_to_other():
    payload = {"document_type": "spaceship_manual", "title": "???", "confidence": 0.5}
    result = parse_and_validate(json.dumps(payload))
    assert result.ok is True
    assert result.document.document_type == "other"


def test_confidence_out_of_range_fails():
    payload = {"document_type": "bill", "title": "Bill", "confidence": 1.5}
    result = parse_and_validate(json.dumps(payload))
    assert result.ok is False


def test_empty_title_fails():
    payload = {"document_type": "bill", "title": "   ", "confidence": 0.8}
    result = parse_and_validate(json.dumps(payload))
    assert result.ok is False


def test_recovers_json_with_stray_preamble_text():
    payload = {"document_type": "warranty", "title": "Laptop Warranty", "confidence": 0.8}
    text = "Sure, here is the extraction:\n" + json.dumps(payload) + "\nLet me know if you need anything else."
    result = parse_and_validate(text)
    assert result.ok is True
    assert result.document.title == "Laptop Warranty"


def test_json_array_instead_of_object_fails_cleanly():
    result = parse_and_validate(json.dumps([{"document_type": "bill"}]))
    assert result.ok is False
    assert "Expected a JSON object" in result.error


def test_no_json_at_all_fails_cleanly():
    result = parse_and_validate("I could not read this document.")
    assert result.ok is False
    assert "No JSON object found" in result.error


def test_balanced_braces_but_invalid_json_syntax_fails_cleanly():
    # Single-quoted keys form a balanced {...} block (so the fallback
    # extractor finds it) but are not valid JSON — must still fail
    # gracefully with a clear message, not raise.
    result = parse_and_validate("Sure: {'document_type': 'bill', 'confidence': 0.5}")
    assert result.ok is False
    assert "invalid JSON" in result.error
