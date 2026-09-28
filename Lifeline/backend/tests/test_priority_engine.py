import sys, os
from datetime import date, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib.priority_engine import classify_item, rank_documents, PriorityLevel


TODAY = date(2026, 9, 16)


def d(days_from_today):
    return (TODAY + timedelta(days=days_from_today)).isoformat()


def test_already_expired_is_urgent():
    r = classify_item(expiry_date=d(-3), document_type="warranty", has_actions=True, confidence=0.9, today=TODAY)
    assert r.level == PriorityLevel.URGENT
    assert r.days_remaining == -3
    assert "3 day" in r.reason


def test_low_confidence_forces_review_regardless_of_date():
    r = classify_item(expiry_date=d(200), document_type="bill", has_actions=False, confidence=0.4, today=TODAY)
    assert r.level == PriorityLevel.NEEDS_REVIEW
    assert r.requires_action is True


def test_no_expiry_date_is_no_action():
    r = classify_item(expiry_date=None, document_type="certificate", has_actions=False, confidence=0.95, today=TODAY)
    assert r.level == PriorityLevel.NO_ACTION


def test_high_stakes_type_gets_wider_urgent_window():
    # 18 days out: "other" type would be attention_soon, but identity
    # documents get a wider urgent cutoff (14+7=21 days).
    generic = classify_item(expiry_date=d(18), document_type="warranty", has_actions=True, confidence=0.9, today=TODAY)
    identity = classify_item(expiry_date=d(18), document_type="identity", has_actions=True, confidence=0.9, today=TODAY)
    assert generic.level == PriorityLevel.ATTENTION_SOON
    assert identity.level == PriorityLevel.URGENT


def test_far_future_is_safe():
    r = classify_item(expiry_date=d(300), document_type="passport", has_actions=False, confidence=0.9, today=TODAY)
    assert r.level == PriorityLevel.SAFE


def test_rank_documents_sorts_urgent_first():
    docs = [
        {"document_id": "a", "document_type": "bill", "confidence": 0.9, "actions": [], "expiry_date": d(200)},
        {"document_id": "b", "document_type": "insurance", "confidence": 0.9, "actions": ["renew"], "expiry_date": d(5)},
        {"document_id": "c", "document_type": "warranty", "confidence": 0.9, "actions": [], "expiry_date": d(45)},
    ]
    ranked = rank_documents(docs, today=TODAY)
    assert [r["document_id"] for r in ranked] == ["b", "c", "a"]
    assert ranked[0]["priority"]["level"] == "urgent"


def test_rank_documents_uses_important_dates_fallback():
    docs = [{
        "document_id": "x", "document_type": "other", "confidence": 0.9, "actions": [],
        "important_dates": [{"date": d(60), "type": "renewal"}, {"date": d(5), "type": "payment_due"}],
    }]
    ranked = rank_documents(docs, today=TODAY)
    # Should pick the earliest date (5 days) -> urgent
    assert ranked[0]["priority"]["level"] == "urgent"
