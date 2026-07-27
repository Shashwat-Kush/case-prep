import json
from pathlib import Path

import pytest

from app.engine.case_flow import CaseComplete, CaseFlow
from app.engine.content_models import Case

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "content"
    / "valid"
    / "cases"
    / "case-cement-profitability.json"
)
PHASES = ["opening", "structuring", "analysis", "synthesis"]


def _case() -> Case:
    return Case.model_validate(json.loads(FIXTURE.read_text()))


def _blob(messages) -> str:
    return "\n".join(m["content"] for m in messages)


def test_full_transition_table():
    flow = CaseFlow(_case())
    seen = [flow.phase_name]
    while not flow.is_terminal:
        seen.append(flow.advance().name)
    assert seen == PHASES
    assert flow.phase_name == "synthesis"
    with pytest.raises(CaseComplete):
        flow.advance()


def test_transitions_only_move_forward_one_step():
    flow = CaseFlow(_case())
    assert flow.phase_name == "opening"
    assert flow.advance().name == "structuring"  # only advance() changes phase


def test_exhibit_phase_gating():
    flow = CaseFlow(_case())  # exhibit unlocks on phase:analysis
    assert not flow.is_unlocked("ex-cost-breakdown")
    flow.advance()  # structuring
    assert not flow.is_unlocked("ex-cost-breakdown")
    flow.advance()  # analysis
    assert flow.is_unlocked("ex-cost-breakdown")
    assert flow.unlocked_exhibit_ids == frozenset({"ex-cost-breakdown"})


def test_locked_exhibit_absent_from_context_then_present():
    flow = CaseFlow(_case())
    flow.advance()  # structuring — still locked
    assert '"freight": 500' not in _blob(flow.context())
    flow.advance()  # analysis — unlocked
    assert '"freight": 500' in _blob(flow.context())


def test_manual_unlock_for_intent_based_exhibit():
    flow = CaseFlow(_case())  # still in opening
    flow.unlock_exhibit("ex-cost-breakdown")
    assert flow.is_unlocked("ex-cost-breakdown")
    with pytest.raises(KeyError):
        flow.unlock_exhibit("ex-does-not-exist")


def test_context_scoped_to_current_phase():
    flow = CaseFlow(_case())
    flow.advance()  # structuring
    blob = _blob(flow.context())
    assert "Probe the candidate's tree." in blob  # current phase instructions
    assert "Ask for a recommendation." not in blob  # synthesis phase
    assert "Reveal the cost exhibit when asked about costs." not in blob  # analysis


def test_transcript_window_limits_turns():
    flow = CaseFlow(_case(), transcript_window_turns=2)
    for i in range(3):
        flow.record_turn("user", f"turn-{i}")
    window = flow.transcript_window()
    assert [m["content"] for m in window] == ["turn-1", "turn-2"]
    blob = _blob(flow.context())
    assert "turn-0" not in blob
    assert "turn-2" in blob


def test_coach_persona_context():
    flow = CaseFlow(_case())
    while flow.phase_name != "analysis":
        flow.advance()
    blob = _blob(flow.context("coach"))
    assert "A strong candidate isolates whether the problem is revenue or cost." in blob
    assert "Renegotiate freight contracts and consider rail." not in blob


def test_no_phases_rejected():
    case = _case()
    case.phases = []
    with pytest.raises(ValueError):
        CaseFlow(case)
