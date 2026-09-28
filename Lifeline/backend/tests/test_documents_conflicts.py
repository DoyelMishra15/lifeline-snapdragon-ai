import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from handlers.documents import _detect_conflicts


def _doc(document_id, document_type, provider, expiry_date, status="processed"):
    return {"document_id": document_id, "document_type": document_type, "provider": provider,
            "expiry_date": expiry_date, "status": status}


def test_same_provider_different_dates_is_a_conflict():
    docs = [
        _doc("a", "insurance", "Acme Insurance", "2026-10-01"),
        _doc("b", "insurance", "acme insurance", "2026-11-15"),  # case-insensitive match
    ]
    conflicts = _detect_conflicts(docs)
    assert len(conflicts) == 1
    assert set(conflicts[0]["conflicting_document_ids"]) == {"a", "b"}


def test_different_providers_no_conflict():
    docs = [
        _doc("a", "insurance", "Acme Insurance", "2026-10-01"),
        _doc("b", "insurance", "Other Insurer", "2026-11-15"),
    ]
    assert _detect_conflicts(docs) == []


def test_no_provider_on_either_side_is_not_grouped_as_conflict():
    # Two unrelated "bill" uploads with no provider detected must not
    # be flagged as conflicting just because they share document_type.
    docs = [
        _doc("a", "bill", None, "2026-10-01"),
        _doc("b", "bill", "", "2026-11-15"),
    ]
    assert _detect_conflicts(docs) == []


def test_unprocessed_documents_are_excluded():
    docs = [
        _doc("a", "insurance", "Acme", "2026-10-01", status="processed"),
        _doc("b", "insurance", "Acme", "2026-11-15", status="uploaded"),
    ]
    assert _detect_conflicts(docs) == []


def test_same_provider_same_date_no_conflict():
    docs = [
        _doc("a", "insurance", "Acme", "2026-10-01"),
        _doc("b", "insurance", "Acme", "2026-10-01"),
    ]
    assert _detect_conflicts(docs) == []
