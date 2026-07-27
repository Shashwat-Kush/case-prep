import json
from pathlib import Path

import pytest

from app.engine.case_flow import CaseFlow, CoachError
from app.engine.content_models import Case

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "content"
    / "valid"
    / "cases"
    / "case-cement-profitability.json"
)
EXPLAIN = "A strong candidate isolates whether the problem is revenue or cost."
REVEAL = "Decompose profit into revenue and cost, then drill into cost lines."


def _case() -> Case:
    return Case.model_validate(json.loads(FIXTURE.read_text()))


def _case_no_coaching() -> Case:
    case = _case()
    for p in case.phases:
        p.coaching = None
    return case


def _blob(messages) -> str:
    return "\n".join(m["content"] for m in messages)


def _at_analysis(mode: str) -> CaseFlow:
    flow = CaseFlow(_case(), mode=mode)
    while flow.phase_name != "analysis":
        flow.advance()
    return flow


def test_guided_refused_without_any_coaching():
    with pytest.raises(ValueError, match="guided mode unavailable"):
        CaseFlow(_case_no_coaching(), mode="guided")


def test_guided_explain_then_attempt_then_reveal():
    flow = _at_analysis("guided")
    assert flow.has_coaching
    assert flow.coach_explain() == EXPLAIN  # verbatim ground truth

    # reveal is blocked before an attempt, in both the API and the context
    with pytest.raises(CoachError):
        flow.coach_reveal()
    assert REVEAL not in _blob(flow.context("coach"))

    flow.record_turn("user", "I think it's the cost side.")
    assert flow.attempted
    assert flow.coach_reveal() == REVEAL  # verbatim ground truth
    assert REVEAL in _blob(flow.context("coach"))


def test_guided_phase_without_coaching_has_no_coach_step():
    flow = CaseFlow(_case(), mode="guided")  # opening has no coaching
    assert not flow.has_coaching
    with pytest.raises(CoachError):
        flow.coach_explain()


def test_standard_mode_unaffected():
    flow = _at_analysis("standard")
    with pytest.raises(CoachError):
        flow.coach_explain()  # coach steps require guided mode
    # interviewer context never carries the model approach anyway
    assert REVEAL not in _blob(flow.context())


def test_attempt_resets_at_each_phase_boundary():
    flow = CaseFlow(_case(), mode="guided")
    flow.record_turn("user", "hi")
    assert flow.attempted
    flow.advance()
    assert not flow.attempted
