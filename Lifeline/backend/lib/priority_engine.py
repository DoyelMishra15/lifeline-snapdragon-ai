"""
Deterministic priority/attention engine.

This is intentionally NOT an LLM call. Bedrock is used for language
understanding (extraction, emergency-plan drafting) but the actual
urgent/attention/upcoming/safe classification is plain, explainable
application logic so it is reproducible, testable and cheap.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class PriorityLevel(str, Enum):
    URGENT = "urgent"
    ATTENTION_SOON = "attention_soon"
    UPCOMING = "upcoming"
    SAFE = "safe"
    NO_ACTION = "no_action"
    NEEDS_REVIEW = "needs_review"

# Category weighting — some document types are inherently higher-stakes
# when they lapse (identity/medical/insurance) than others (subscriptions).
HIGH_STAKES_TYPES = {"identity", "passport", "insurance", "medical", "legal"}

URGENT_DAYS = 14
ATTENTION_DAYS = 30
UPCOMING_DAYS = 90
LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class PriorityResult:
    level: PriorityLevel
    days_remaining: int | None
    reason: str
    requires_action: bool


def _days_until(target: str, today: date | None = None) -> int:
    today = today or date.today()
    target_date = datetime.strptime(target, "%Y-%m-%d").date()
    return (target_date - today).days


def classify_item(
    *,
    expiry_date: str | None,
    document_type: str,
    has_actions: bool,
    confidence: float,
    today: date | None = None,
) -> PriorityResult:
    """
    Classify a single dated item into a priority level with a
    human-readable, explainable reason string.
    """
    if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
        return PriorityResult(
            level=PriorityLevel.NEEDS_REVIEW,
            days_remaining=None,
            reason=(
                f"Extraction confidence is low ({confidence:.0%}); "
                "please verify this document manually."
            ),
            requires_action=True,
        )

    if not expiry_date:
        return PriorityResult(
            level=PriorityLevel.NO_ACTION,
            days_remaining=None,
            reason="No dated deadline was found on this document.",
            requires_action=False,
        )

    days = _days_until(expiry_date, today=today)
    high_stakes = document_type in HIGH_STAKES_TYPES

    if days < 0:
        return PriorityResult(
            level=PriorityLevel.URGENT,
            days_remaining=days,
            reason=f"This already expired {abs(days)} day(s) ago and needs immediate attention.",
            requires_action=True,
        )

    urgent_cutoff = URGENT_DAYS + (7 if high_stakes else 0)
    attention_cutoff = ATTENTION_DAYS + (14 if high_stakes else 0)
    upcoming_cutoff = UPCOMING_DAYS

    if days <= urgent_cutoff:
        return PriorityResult(
            level=PriorityLevel.URGENT,
            days_remaining=days,
            reason=(
                f"High attention because this expires in {days} day(s)"
                + (" and requires renewal." if has_actions else ".")
            ),
            requires_action=True,
        )
    if days <= attention_cutoff:
        return PriorityResult(
            level=PriorityLevel.ATTENTION_SOON,
            days_remaining=days,
            reason=f"Expires in {days} days — worth planning for soon.",
            requires_action=has_actions,
        )
    if days <= upcoming_cutoff:
        return PriorityResult(
            level=PriorityLevel.UPCOMING,
            days_remaining=days,
            reason=f"Expires in {days} days — on the radar, no action needed yet.",
            requires_action=False,
        )

    return PriorityResult(
        level=PriorityLevel.SAFE,
        days_remaining=days,
        reason=f"Valid for {days} more days.",
        requires_action=False,
    )


def rank_documents(documents: list[dict], today: date | None = None) -> list[dict]:
    """
    Given a list of document metadata dicts (as stored in DynamoDB),
    attach a `priority` block to each and sort urgent-first.
    Expected keys per doc: document_type, confidence, actions (list),
    and either expiry_date or important_dates (list of {date, type}).
    """
    order = {
        PriorityLevel.URGENT: 0,
        PriorityLevel.NEEDS_REVIEW: 1,
        PriorityLevel.ATTENTION_SOON: 2,
        PriorityLevel.UPCOMING: 3,
        PriorityLevel.SAFE: 4,
        PriorityLevel.NO_ACTION: 5,
    }
    out = []
    for doc in documents:
        expiry = doc.get("expiry_date")
        if not expiry:
            dates = doc.get("important_dates") or []
            if dates:
                expiry = sorted(d["date"] for d in dates)[0]
        result = classify_item(
            expiry_date=expiry,
            document_type=doc.get("document_type", "other"),
            has_actions=bool(doc.get("actions")),
            confidence=doc.get("confidence", 1.0),
            today=today,
        )
        enriched = {**doc, "priority": {
            "level": result.level.value,
            "days_remaining": result.days_remaining,
            "reason": result.reason,
            "requires_action": result.requires_action,
        }}
        out.append(enriched)

    out.sort(key=lambda d: (order[PriorityLevel(d["priority"]["level"])],
                             d["priority"]["days_remaining"] if d["priority"]["days_remaining"] is not None else 9999))
    return out
