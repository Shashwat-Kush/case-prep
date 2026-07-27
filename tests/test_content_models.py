import pytest
from pydantic import ValidationError

from app.engine.content_models import (
    Benchmarks,
    Case,
    Guesstimate,
    Lesson,
)


def _dim():
    return {"anchors": {1: "weak", 3: "ok", 5: "strong"}}


def _case():
    return {
        "meta": {
            "id": "case-cement-profitability",
            "title": "Cement profitability",
            "type": "profitability",
            "industry": "cement",
            "difficulty": "medium",
            "est_minutes": 30,
        },
        "prompt": "Your client makes cement.",
        "phases": [{"name": "opening", "interviewer_instructions": "Read the prompt."}],
        "model_answer": {
            "framework": "profit tree",
            "key_insights": ["costs rose"],
            "recommendation": "cut costs",
            "walkthrough": "...",
        },
        "rubric": {
            d: _dim()
            for d in ("structure", "math", "judgment", "communication", "synthesis")
        },
    }


def _guess():
    return {
        "meta": {
            "id": "guess-petrol-pumps-delhi",
            "title": "Petrol pumps in Delhi",
            "difficulty": "easy",
            "est_minutes": 15,
            "region": "india",
        },
        "prompt": "How many petrol pumps in Delhi?",
        "approach": {
            "recommended": "top_down",
            "tree": [{"segment": "population", "derivation": "given", "value": 2.0e7}],
        },
        "answer_range": {"low": 400, "high": 800},
        "rubric": {
            d: _dim()
            for d in ("approach", "segmentation", "arithmetic", "sanity_check")
        },
    }


def _lesson():
    return {
        "meta": {
            "id": "lesson-profitability",
            "title": "Profitability",
            "concepts_taught": ["profit-tree"],
        },
        "sections": [{"heading": "Intro", "content": "..."}],
        "when_to_use": "declining profit",
        "when_not_to_use": "market sizing",
        "quiz": [
            {
                "question": "Q",
                "options": ["a", "b"],
                "answer": "a",
                "explanation": "because",
            }
        ],
    }


def test_minimal_valid_fixtures_parse():
    assert Case.model_validate(_case()).meta.id == "case-cement-profitability"
    assert Guesstimate.model_validate(_guess()).approach.recommended.value == "top_down"
    assert Lesson.model_validate(_lesson()).meta.concepts_taught == ["profit-tree"]


def test_benchmarks_parse_and_lookup():
    b = Benchmarks.model_validate(
        {"india_population": {"value": 1.45e9, "unit": "people", "as_of": 2026}}
    )
    assert "india_population" in b
    assert b["india_population"].value == 1.45e9


@pytest.mark.parametrize("field", ["prompt", "phases", "model_answer", "rubric"])
def test_case_missing_required_field_rejected(field):
    data = _case()
    del data[field]
    with pytest.raises(ValidationError):
        Case.model_validate(data)


@pytest.mark.parametrize(
    "bad_id", ["cement-profitability", "case-Cement", "case-", "case-a_b", "guess-x"]
)
def test_case_id_pattern_enforced(bad_id):
    data = _case()
    data["meta"]["id"] = bad_id
    with pytest.raises(ValidationError):
        Case.model_validate(data)


def test_guess_and_lesson_id_prefixes():
    g = _guess()
    g["meta"]["id"] = "case-wrong-prefix"
    with pytest.raises(ValidationError):
        Guesstimate.model_validate(g)
    lesson = _lesson()
    lesson["meta"]["id"] = "profitability"
    with pytest.raises(ValidationError):
        Lesson.model_validate(lesson)
