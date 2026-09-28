import sys, os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from handlers.emergency import validate_plan


def test_valid_plan_passes_through():
    raw = {
        "situation": "Lost my wallet/documents",
        "summary": "Secure identity and payment documents.",
        "steps": [
            {"order": 1, "action": "Check passport status", "why": "Identity doc",
             "source_document_ids": ["doc-1"]},
        ],
        "relevant_documents": ["doc-1"],
        "missing_information": [],
    }
    plan = validate_plan(raw, valid_document_ids={"doc-1", "doc-2"})
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["source_document_ids"] == ["doc-1"]
    assert "does not diagnose" in plan["disclaimer"]


def test_hallucinated_document_ids_are_stripped():
    raw = {
        "situation": "Lost my phone",
        "summary": "s",
        "steps": [
            {"order": 1, "action": "a", "why": "w", "source_document_ids": ["doc-1", "doc-FAKE"]},
        ],
        "relevant_documents": ["doc-1", "doc-FAKE"],
        "missing_information": [],
    }
    plan = validate_plan(raw, valid_document_ids={"doc-1"})
    assert plan["steps"][0]["source_document_ids"] == ["doc-1"]
    assert plan["relevant_documents"] == ["doc-1"]


def test_disclaimer_is_always_present_even_if_model_omits_it():
    raw = {"situation": "x", "summary": "s", "steps": [], "relevant_documents": [], "missing_information": []}
    plan = validate_plan(raw, valid_document_ids=set())
    assert "does not" in plan["disclaimer"].lower()


def test_steps_are_renumbered_sequentially():
    raw = {
        "situation": "x", "summary": "s",
        "steps": [{"order": 5, "action": "a1", "why": "w"}, {"order": 1, "action": "a2", "why": "w"}],
        "relevant_documents": [], "missing_information": [],
    }
    plan = validate_plan(raw, valid_document_ids=set())
    assert [s["order"] for s in plan["steps"]] == [1, 2]


def test_malformed_step_is_dropped_not_crashed():
    raw = {
        "situation": "x", "summary": "s",
        "steps": ["not a dict", {"action": "valid", "why": "w"}, 42],
        "relevant_documents": [], "missing_information": [],
    }
    plan = validate_plan(raw, valid_document_ids=set())
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["action"] == "valid"


def test_non_list_steps_field_does_not_crash():
    raw = {"situation": "x", "summary": "s", "steps": "not a list",
           "relevant_documents": "also not a list", "missing_information": None}
    plan = validate_plan(raw, valid_document_ids=set())
    assert plan["steps"] == []
    assert plan["relevant_documents"] == []
    assert plan["missing_information"] == []


def test_non_string_source_document_ids_are_filtered():
    raw = {
        "situation": "x", "summary": "s",
        "steps": [{"action": "a", "why": "w", "source_document_ids": ["doc-1", 42, None, "doc-2"]}],
        "relevant_documents": [], "missing_information": [],
    }
    plan = validate_plan(raw, valid_document_ids={"doc-1", "doc-2"})
    assert plan["steps"][0]["source_document_ids"] == ["doc-1", "doc-2"]
