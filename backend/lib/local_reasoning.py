"""
Local, fully-offline AI provider — the LIFELINE_AI_PROVIDER=local
backend behind lib/ai_provider.py.

This is what actually runs LifeLine's "understand" and "respond"
stages inside GitHub Codespaces / SAM-local + LocalStack, where there
is no real AWS account and therefore no access to Amazon Bedrock.
Rather than faking success or stubbing the pipeline out, this module
does the real work with open-source, offline tools:

- extract_document(): regex/keyword-based structured extraction over
  real document text (from lib/pdf_extract.py for PDFs, or from
  lib/ocr.py's Tesseract OCR output for images). It genuinely reads
  dates, amounts, a provider name, and a document type out of
  whatever text it's given — it does not look at the filename and
  does not fabricate anything it can't find; missing fields are
  reported as warnings, matching the same "never invent facts"
  philosophy as the Bedrock system prompts.
- draft_emergency_plan(): the same situation-specific action-plan
  templates used previously in the frontend's mock/demo mode,
  now implemented as real backend logic that reasons over the user's
  actually-stored documents (not filenames) via
  backend/handlers/emergency.py's context payload.

Both functions return the exact same {"ok": True, "text": "<json>"}
shape lib/bedrock_client.py returns, so nothing downstream (schema
validation, handlers/process.py, handlers/emergency.py's
validate_plan()) needs to know which engine actually ran.
"""
from __future__ import annotations

import json
import re
from datetime import date

from lib import ocr
from lib.situations import LABEL_TO_KEY

# ---------------------------------------------------------------
# Document type detection
# ---------------------------------------------------------------

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "insurance": ["insurance", "policy", "premium", "insurer", "insured", "coverage", "policyholder"],
    "passport": ["passport", "nationality", "place of birth", "date of issue", "passport no"],
    "identity": ["identity card", "national id", "driving licence", "driver's license", "aadhaar",
                 "social security", "identification number"],
    "warranty": ["warranty", "warranted", "guarantee period", "warranty card", "service warranty"],
    "bill": ["invoice", "bill", "amount due", "payment due", "statement", "utility"],
    "subscription": ["subscription", "auto-renew", "auto renew", "billing cycle", "renews on", "membership"],
    "certificate": ["certificate", "certify", "certification", "awarded to", "this is to certify"],
    "medical": ["diagnosis", "prescription", "patient", "physician", "hospital", "medical record", "clinic"],
    "financial": ["account number", "bank statement", "loan", "interest rate", "credit", "financial"],
    "legal": ["agreement", "contract", "hereby", "witnesseth", "party of the first part", "legal notice"],
}

_ACTIONS_BY_TYPE: dict[str, str] = {
    "insurance": "Renew before expiry",
    "warranty": "Consider extended warranty before it lapses",
    "subscription": "Cancel or renew before the next billing cycle",
    "bill": "Pay before the due date",
    "passport": "Start renewal early — passport processing can take weeks",
    "identity": "Renew before expiry to avoid a lapse in valid ID",
    "certificate": "Check if renewal or recertification is required",
    "medical": "Follow up with the provider before this date",
    "financial": "Review terms before this date",
    "legal": "Review the agreement before this date",
}

# ---------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Each pattern captures a date; the surrounding line text (not just the
# match) is inspected afterward for an expiry/renewal/due/issue keyword.
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),                      # 2026-10-14
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"),                    # 14/10/2026 or 10/14/2026
    re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b"),                    # 14-10-2026
    re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun[e]?|jul[y]?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})\b",
        re.IGNORECASE,
    ),  # 14 October 2026
    re.compile(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun[e]?|jul[y]?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
        re.IGNORECASE,
    ),  # October 14, 2026 / October 14 2026
]

_EXPIRY_HINTS = ["expiry", "expires", "expiration", "valid until", "valid till", "valid thru", "valid through"]
_RENEWAL_HINTS = ["renewal", "renew", "renews on", "next billing"]
_DUE_HINTS = ["due date", "payment due", "amount due by", "due by"]
_ISSUE_HINTS = ["date of issue", "issue date", "issued on", "issued"]

_AMOUNT_RE = re.compile(r"(₹|\$|€|£|Rs\.?)\s?([\d]{1,3}(?:[,\d]{0,10})?(?:\.\d{1,2})?)")

_PROVIDER_LABEL_RE = re.compile(
    r"(?:provider|insurer|insured with|issued by|issuing authority|bank|company|manufacturer)\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)
_PROVIDER_SUFFIX_RE = re.compile(
    r"^[A-Z][A-Za-z0-9&.,'\- ]{2,60}\b(Insurance|Bank|Inc\.?|Ltd\.?|LLC|Corp\.?|Company|Co\.|Pvt\.?)\b"
)

MIN_MEANINGFUL_TEXT_CHARS = 30


def _try_normalize_date(year: int, month: int, day: int) -> str | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _find_dates(text: str) -> list[dict]:
    """
    Returns a list of {"date": "YYYY-MM-DD", "type": "...", "description": "..."}
    for every recognizable date in the text, deduplicated by date+type.
    """
    found: dict[tuple[str, str], dict] = {}
    lines = text.splitlines() or [text]

    for line in lines:
        lower_line = line.lower()
        for pattern in _DATE_PATTERNS:
            for m in pattern.finditer(line):
                groups = m.groups()
                iso = None
                if len(groups) == 3 and groups[0].isdigit() and len(groups[0]) == 4:
                    iso = _try_normalize_date(int(groups[0]), int(groups[1]), int(groups[2]))
                elif len(groups) == 3 and groups[0].isdigit() and groups[2].isdigit() and not groups[1].isdigit():
                    # DD Month YYYY
                    month = _MONTHS.get(groups[1].lower()[:3]) or _MONTHS.get(groups[1].lower())
                    if month:
                        iso = _try_normalize_date(int(groups[2]), month, int(groups[0]))
                elif len(groups) == 3 and not groups[0].isdigit():
                    # Month DD, YYYY
                    month = _MONTHS.get(groups[0].lower()[:3]) or _MONTHS.get(groups[0].lower())
                    if month:
                        iso = _try_normalize_date(int(groups[2]), month, int(groups[1]))
                elif len(groups) == 3 and groups[0].isdigit() and groups[1].isdigit() and groups[2].isdigit():
                    # Ambiguous D/M/Y vs M/D/Y — prefer day-first (matches
                    # how most non-US documents in this domain are
                    # written); fall back to month-first if impossible.
                    a, b, y = int(groups[0]), int(groups[1]), int(groups[2])
                    iso = _try_normalize_date(y, b, a) if a <= 31 and b <= 12 else None
                    if iso is None:
                        iso = _try_normalize_date(y, a, b)

                if not iso:
                    continue

                if any(h in lower_line for h in _EXPIRY_HINTS):
                    date_type = "expiry"
                elif any(h in lower_line for h in _RENEWAL_HINTS):
                    date_type = "renewal"
                elif any(h in lower_line for h in _DUE_HINTS):
                    date_type = "payment_due"
                elif any(h in lower_line for h in _ISSUE_HINTS):
                    date_type = "issue"
                else:
                    date_type = "other"

                key = (iso, date_type)
                if key not in found:
                    found[key] = {"date": iso, "type": date_type, "description": line.strip()[:120]}

    return list(found.values())


def _detect_document_type(lower_text: str) -> tuple[str, int]:
    best_type, best_score = "other", 0
    for doc_type, keywords in _TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower_text)
        if score > best_score:
            best_type, best_score = doc_type, score
    return best_type, best_score


def _detect_title(lines: list[str]) -> str:
    for line in lines[:8]:
        candidate = line.strip()
        if len(candidate) >= 4 and not candidate.isdigit() and any(c.isalpha() for c in candidate):
            return candidate[:200]
    return "Uploaded Document"


def _detect_provider(text: str, lines: list[str]) -> str | None:
    m = _PROVIDER_LABEL_RE.search(text)
    if m:
        candidate = m.group(1).strip().strip(".")
        if candidate:
            return candidate[:120]
    for line in lines[:15]:
        m = _PROVIDER_SUFFIX_RE.match(line.strip())
        if m:
            return line.strip()[:120]
    return None


def _detect_amount(text: str) -> str | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


def _pick_expiry_date(dates: list[dict]) -> str | None:
    for preferred_type in ("expiry", "renewal", "payment_due"):
        candidates = sorted(d["date"] for d in dates if d["type"] == preferred_type)
        if candidates:
            return candidates[0]
    return None


def _extract_from_text(raw_text: str) -> dict:
    text = raw_text or ""
    lower_text = text.lower()
    lines = [l for l in text.splitlines() if l.strip()]

    if len(text.strip()) < MIN_MEANINGFUL_TEXT_CHARS:
        return {
            "document_type": "other",
            "title": "Uploaded Document",
            "provider": None,
            "expiry_date": None,
            "important_dates": [],
            "amount": None,
            "actions": [],
            "relevant_entities": [],
            "warnings": ["Very little readable text was found in this document — "
                         "please review the details and add anything important manually."],
            "confidence": 0.3,
        }

    warnings: list[str] = []
    document_type, type_score = _detect_document_type(lower_text)
    title = _detect_title(lines)
    provider = _detect_provider(text, lines)
    amount = _detect_amount(text)
    dates = _find_dates(text)
    expiry_date = _pick_expiry_date(dates)

    actions = []
    if expiry_date and document_type in _ACTIONS_BY_TYPE:
        actions.append(_ACTIONS_BY_TYPE[document_type])

    confidence = 0.5
    if type_score > 0:
        confidence += 0.15
    if expiry_date:
        confidence += 0.15
    if provider:
        confidence += 0.1
    if amount:
        confidence += 0.1
    confidence = min(confidence, 0.95)

    if document_type in ("insurance", "warranty", "subscription", "bill", "certificate",
                          "identity", "passport") and not expiry_date:
        warnings.append("No expiry, renewal, or due date was detected — check the document "
                         "and add one manually if it has one.")
    if not provider:
        warnings.append("No provider/issuer name was detected.")

    return {
        "document_type": document_type,
        "title": title,
        "provider": provider,
        "expiry_date": expiry_date,
        "important_dates": [{"date": d["date"], "type": d["type"], "description": d["description"]} for d in dates],
        "amount": amount,
        "actions": actions,
        "relevant_entities": [provider] if provider else [],
        "warnings": warnings,
        "confidence": round(confidence, 2),
    }


def extract_document(*, text: str | None = None, image_bytes: bytes | None = None,
                      image_media_type: str = "image/png") -> dict:
    """
    Same contract as bedrock_client.extract_document(): returns
    {"ok": True, "text": "<json>"} on success, or {"ok": False,
    "error": "...", "retryable": bool} only when the input genuinely
    can't be processed at all (e.g. OCR itself fails) — low-confidence
    or empty-content results are still "ok" so the demo flow reaches
    schema validation / needs_review instead of dead-ending in the AI
    layer, exactly like a low-confidence Bedrock extraction would.
    """
    if image_bytes is not None:
        try:
            ocr_text = ocr.extract_text_from_image(image_bytes)
        except ocr.OcrError as e:
            return {"ok": False, "error": str(e), "retryable": False}
        extracted = _extract_from_text(ocr_text)
    else:
        extracted = _extract_from_text(text or "")

    return {"ok": True, "text": json.dumps(extracted)}


# ---------------------------------------------------------------
# Emergency plan templates
# ---------------------------------------------------------------

_PLAN_TEMPLATES: dict[str, dict] = {
    "lost_wallet": {
        "summary": "Secure your identity and payment documents and know what needs replacing.",
        "relevant_types": ["identity", "passport", "insurance", "financial"],
        "steps": [
            ("Note which identity/payment documents were in the wallet",
             "Determines what needs replacing and where to report the loss."),
            ("Check your stored emergency contact", "They may need to help coordinate replacements."),
            ("Review stored insurance details for any card-protection cover",
             "Some policies cover fraudulent use after a lost card."),
            ("List documents that will need reissue", "Passport/ID reissue often has its own timeline."),
        ],
    },
    "lost_phone": {
        "summary": "Lock down accounts tied to your phone number and preserve access to key documents.",
        "relevant_types": ["identity", "financial"],
        "steps": [
            ("Ask your carrier to suspend the SIM", "Prevents SIM-based account takeover."),
            ("Check which stored documents reference this phone number for two-factor logins",
             "Those accounts need an alternate recovery method."),
            ("Review your stored emergency contact", "They may need an alternate way to reach you."),
        ],
    },
    "medical_emergency": {
        "summary": "Surface the documents someone would need if they were helping you right now.",
        "relevant_types": ["medical", "insurance", "identity"],
        "steps": [
            ("Share stored health insurance details with whoever is assisting you",
             "Needed for hospital admission and billing."),
            ("Provide your stored emergency contact information", "Hospitals typically require a contact on file."),
            ("Have identity documents ready for admission paperwork", "Required for hospital registration."),
        ],
    },
    "temporarily_unavailable": {
        "summary": "Make sure anything time-sensitive keeps moving while you are unreachable.",
        "relevant_types": ["bill", "subscription", "insurance"],
        "steps": [
            ("Review upcoming deadlines in the next two weeks", "These will need handling before you are back."),
            ("Share access instructions with a trusted contact if needed", "So nothing lapses while you are away."),
        ],
    },
    "travel_emergency": {
        "summary": "Get your identity and insurance documents in front of you fast.",
        "relevant_types": ["passport", "identity", "insurance"],
        "steps": [
            ("Pull up your passport / identity document details",
             "Often requested by local authorities or embassies."),
            ("Check travel insurance coverage and provider contact",
             "Needed to file a claim or request assistance."),
            ("Share your stored emergency contact with anyone assisting you", "They may need to be reached."),
        ],
    },
    "other": {
        "summary": "Here is what LifeLine has on file that may be relevant.",
        "relevant_types": [],
        "steps": [
            ("Review your stored documents below", "Starting point for figuring out next steps."),
        ],
    },
}


def draft_emergency_plan(*, situation: str, user_data: dict) -> dict:
    """
    Same contract as bedrock_client.draft_emergency_plan(): returns
    {"ok": True, "text": "<json>"}. `situation` is the human-readable
    label handlers/emergency.py builds from lib/situations.py; mapped
    back to its key here to pick a template. Reasons only over
    user_data["documents"]/["emergency_contact"] — never invents a
    document, exactly like the Bedrock system prompt requires.
    """
    situation_key = LABEL_TO_KEY.get(situation, "other")
    template = _PLAN_TEMPLATES.get(situation_key, _PLAN_TEMPLATES["other"])

    documents = user_data.get("documents") or []
    relevant_types = template["relevant_types"]
    relevant_docs = (
        [d for d in documents if d.get("document_type") in relevant_types]
        if relevant_types else list(documents)
    )
    relevant_ids = [d["document_id"] for d in relevant_docs if d.get("document_id")]

    steps = [
        {"order": i, "action": action, "why": why, "source_document_ids": relevant_ids}
        for i, (action, why) in enumerate(template["steps"], start=1)
    ]

    missing_information = []
    if relevant_types and not relevant_docs:
        missing_information.append("No relevant documents are on file yet for this situation.")
    if not user_data.get("emergency_contact"):
        missing_information.append("No emergency contact is saved — add one in Settings.")

    plan = {
        "situation": situation,
        "summary": template["summary"],
        "steps": steps,
        "relevant_documents": relevant_ids,
        "missing_information": missing_information,
        "disclaimer": (
            "LifeLine prepares information and next steps for you to act on. "
            "It does not diagnose medical conditions, provide treatment advice, "
            "move money, or contact anyone on your behalf."
        ),
    }
    return {"ok": True, "text": json.dumps(plan)}
