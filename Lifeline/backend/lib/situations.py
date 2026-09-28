"""
Canonical emergency-mode situation keys and their human-readable
labels. Shared by handlers/emergency.py (validates the incoming
situation key and builds the Bedrock/local-reasoning prompt) and
lib/local_reasoning.py (maps a label back to a key to pick the right
plan template) so the two never drift out of sync.
"""
from __future__ import annotations

SITUATIONS: dict[str, str] = {
    "lost_phone": "Lost my phone",
    "lost_wallet": "Lost my wallet/documents",
    "medical_emergency": "Hospital / medical emergency",
    "temporarily_unavailable": "I'm temporarily unavailable",
    "travel_emergency": "Travel emergency",
    "other": "Other",
}

LABEL_TO_KEY: dict[str, str] = {label: key for key, label in SITUATIONS.items()}
