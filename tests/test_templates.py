import json
from pathlib import Path

import pytest

from app.engine.content_models import Case
from app.llm.templates import (
    build_coach_context,
    build_interviewer_context,
    render,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "content"
    / "valid"
    / "cases"
    / "case-cement-profitability.json"
)


def _case() -> Case:
    return Case.model_validate(json.loads(FIXTURE.read_text()))


# Strings that must never reach the interviewer (from the fixture's solution fields).
SOLUTION_STRINGS = [
    "Renegotiate freight contracts and consider rail.",  # model_answer.recommendation
    "Profit fell because freight rose; revenue was stable.",  # model_answer.walkthrough
    "Freight is the largest and fastest-growing cost line.",  # exhibit.so_what
    "A strong candidate isolates whether the problem is revenue or cost.",  # coaching
    "Decompose profit into revenue and cost",  # coaching.model_approach_for_phase
    "MECE tree tailored to cement",  # rubric anchor
    "divided by cost instead of revenue",  # checkpoint common_error
]


def _joined(messages) -> str:
    return "\n".join(m["content"] for m in messages)


def test_render_substitutes_variable():
    out = render("interviewer", pushback_intensity="aggressive")
    assert "aggressive" in out
    assert "$pushback_intensity" not in out


def test_render_missing_variable_raises():
    with pytest.raises(KeyError):
        render("interviewer")


def test_render_template_without_variables():
    assert "coach" in render("coach").lower()


def test_interviewer_context_excludes_all_solution_content():
    # Even with the exhibit unlocked, no solution field may appear.
    messages = build_interviewer_context(
        _case(),
        phase_name="analysis",
        unlocked_exhibit_ids=["ex-cost-breakdown"],
        transcript=[{"role": "user", "content": "What are the costs?"}],
    )
    blob = _joined(messages)
    for s in SOLUTION_STRINGS:
        assert s not in blob, f"leaked solution content: {s!r}"
    # positive controls: the prompt and this phase's instructions are present
    assert "cement manufacturer whose profits have fallen" in blob
    assert "Reveal the cost exhibit when asked about costs." in blob


def test_interviewer_reveals_unlocked_exhibit_data_but_not_so_what():
    messages = build_interviewer_context(
        _case(), phase_name="analysis", unlocked_exhibit_ids=["ex-cost-breakdown"]
    )
    blob = _joined(messages)
    assert '"freight": 500' in blob  # exhibit data is shown
    assert "fastest-growing" not in blob  # its so_what is not


def test_interviewer_hides_locked_exhibit():
    messages = build_interviewer_context(_case(), phase_name="analysis")
    blob = _joined(messages)
    assert "Cost breakdown" not in blob
    assert '"freight": 500' not in blob


def test_coach_context_includes_coaching_but_not_model_answer():
    messages = build_coach_context(_case(), phase_name="analysis")
    blob = _joined(messages)
    assert "A strong candidate isolates whether the problem is revenue or cost." in blob
    assert "Renegotiate freight contracts and consider rail." not in blob
