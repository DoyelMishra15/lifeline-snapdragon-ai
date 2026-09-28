import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import ai_provider


def test_defaults_to_bedrock_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("LIFELINE_AI_PROVIDER", raising=False)
    assert ai_provider.current_provider() == "bedrock"
    from lib import bedrock_client
    assert ai_provider._backend() is bedrock_client


def test_selects_local_provider_when_env_var_set(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    assert ai_provider.current_provider() == "local"
    from lib import local_reasoning
    assert ai_provider._backend() is local_reasoning


def test_local_provider_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "  Local  ")
    assert ai_provider.current_provider() == "local"


def test_provider_choice_is_read_fresh_every_call_not_cached(monkeypatch):
    # Regression test: PROVIDER must never be bound once at import time —
    # doing so previously leaked "local" mode into unrelated tests/
    # requests that never opted into it.
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    from lib import local_reasoning
    assert ai_provider._backend() is local_reasoning

    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "bedrock")
    from lib import bedrock_client
    assert ai_provider._backend() is bedrock_client


def test_extract_document_delegates_to_selected_backend(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    result = ai_provider.extract_document(text="Insurance Policy\nExpires 2026-10-14\nProvider: Acme Insurance")
    assert result["ok"] is True


def test_draft_emergency_plan_delegates_to_selected_backend(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    result = ai_provider.draft_emergency_plan(situation="Other", user_data={"documents": []})
    assert result["ok"] is True


def test_selects_snapdragon_provider_when_env_var_set(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "snapdragon")
    assert ai_provider.current_provider() == "snapdragon"
    from lib import snapdragon_provider
    assert ai_provider._backend() is snapdragon_provider


def test_snapdragon_extract_document_from_text_delegates(monkeypatch):
    # Text-only extraction never touches the optional onnxruntime/
    # rapidocr dependency (see lib/snapdragon_provider.py), so this
    # works regardless of whether requirements-snapdragon.txt is
    # installed — unlike the image-path tests in
    # tests/test_snapdragon_provider.py, which skip without it.
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "snapdragon")
    result = ai_provider.extract_document(text="Insurance Policy\nExpires 2026-10-14\nProvider: Acme Insurance")
    assert result["ok"] is True


def test_runtime_status_returns_none_for_backends_without_one(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "local")
    assert ai_provider.runtime_status() is None

    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "bedrock")
    assert ai_provider.runtime_status() is None


def test_runtime_status_delegates_to_snapdragon_provider(monkeypatch):
    monkeypatch.setenv("LIFELINE_AI_PROVIDER", "snapdragon")
    monkeypatch.setenv("LIFELINE_OCR_EXECUTION_MODE", "cpu")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("rapidocr_onnxruntime")
    status = ai_provider.runtime_status()
    assert status is not None
    assert status["resolved_mode"] == "cpu"
