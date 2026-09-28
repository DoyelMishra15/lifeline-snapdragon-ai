"""
Structured-output schema for document extraction.

Bedrock returns free-form JSON text. We NEVER trust it directly —
every extraction is parsed and validated against this schema before
it is allowed to reach DynamoDB or the UI. Anything that fails
validation is stored as a failed/needs-review extraction instead of
being silently dropped or guessed at.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

VALID_DOCUMENT_TYPES = {
    "insurance",
    "identity",
    "passport",
    "warranty",
    "bill",
    "subscription",
    "certificate",
    "medical",
    "financial",
    "legal",
    "other",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if not DATE_RE.match(v):
        raise ValueError(f"date must be YYYY-MM-DD, got {v!r}")
    # Raises ValueError itself if not a real calendar date.
    date.fromisoformat(v)
    return v


class ImportantDate(BaseModel):
    date: str
    type: str = Field(description="e.g. expiry, renewal, payment_due, issue")
    description: str = ""

    @field_validator("date")
    @classmethod
    def check_date(cls, v):
        return _validate_date_str(v)


class ExtractedDocument(BaseModel):
    """Validated shape of a Bedrock document-extraction result."""

    document_type: str
    title: str
    provider: Optional[str] = None
    expiry_date: Optional[str] = None
    important_dates: list[ImportantDate] = Field(default_factory=list)
    amount: Optional[str] = None
    actions: list[str] = Field(default_factory=list)
    relevant_entities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("document_type")
    @classmethod
    def check_doc_type(cls, v):
        v = (v or "other").lower().strip()
        return v if v in VALID_DOCUMENT_TYPES else "other"

    @field_validator("expiry_date")
    @classmethod
    def check_expiry(cls, v):
        return _validate_date_str(v)

    @field_validator("title")
    @classmethod
    def check_title(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("title must not be empty")
        return v[:200]


class ValidationResult(BaseModel):
    ok: bool
    document: Optional[ExtractedDocument] = None
    error: Optional[str] = None
    raw_text: Optional[str] = None


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def _extract_first_json_object(text: str) -> str | None:
    """
    Best-effort fallback for when the model adds stray prose before/after
    the JSON despite instructions not to. Finds the first balanced
    {...} block by brace counting (ignoring braces inside string
    literals) rather than trusting a naive regex, since document text
    embedded in the JSON may itself contain braces.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_and_validate(model_output_text: str) -> ValidationResult:
    """
    Parse raw Bedrock text output and validate it into an
    ExtractedDocument. Never raises — always returns a ValidationResult
    so callers can store a "needs review" record instead of crashing
    the pipeline or fabricating a fallback document.
    """
    cleaned = _strip_code_fences(model_output_text or "")

    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: the model may have added stray text around the JSON
        # despite instructions not to. Try to pull out the first balanced
        # JSON object before giving up.
        candidate = _extract_first_json_object(cleaned)
        if candidate is None:
            return ValidationResult(ok=False, error="No JSON object found in model output", raw_text=model_output_text)
        try:
            raw = json.loads(candidate)
        except json.JSONDecodeError as e:
            return ValidationResult(ok=False, error=f"invalid JSON: {e}", raw_text=model_output_text)

    if not isinstance(raw, dict):
        return ValidationResult(ok=False, error=f"Expected a JSON object, got {type(raw).__name__}",
                                 raw_text=model_output_text)

    try:
        doc = ExtractedDocument.model_validate(raw)
    except ValidationError as e:
        return ValidationResult(ok=False, error=str(e), raw_text=model_output_text)

    return ValidationResult(ok=True, document=doc)
