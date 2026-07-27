import json
from pathlib import Path

import pytest

from app.engine.content_models import Guesstimate
from app.engine.guess_flow import GuessComplete, GuessFlow, GuessFlowError

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "content"
    / "valid"
    / "guesstimates"
    / "guess-petrol-pumps-delhi.json"
)
SEGMENTS = ["delhi_pop", "cars", "pumps"]


def _guess() -> Guesstimate:
    return Guesstimate.model_validate(json.loads(FIXTURE.read_text()))


def test_transition_table():
    flow = GuessFlow(_guess())
    assert flow.step == "clarify"
    assert flow.advance() == "approach"
    assert flow.advance() == "segmentation"
    assert flow.advance() == "estimation"
    # estimation is progressed by submitting per-segment estimates
    for i, seg in enumerate(SEGMENTS):
        assert flow.current_segment.segment == seg
        flow.submit_estimate(float(i + 1))
    assert flow.step == "sanity_check"  # auto-moved after the last segment
    assert flow.advance() == "complete"
    assert flow.is_complete
    with pytest.raises(GuessComplete):
        flow.advance()


def test_cannot_advance_through_estimation():
    flow = GuessFlow(_guess())
    flow.advance()  # approach
    flow.advance()  # segmentation
    flow.advance()  # estimation
    with pytest.raises(GuessFlowError):
        flow.advance()


def test_submit_estimate_only_during_estimation():
    flow = GuessFlow(_guess())  # in clarify
    with pytest.raises(GuessFlowError):
        flow.submit_estimate(1.0)


def test_segment_estimates_captured_as_structured_numbers():
    flow = GuessFlow(_guess())
    for _ in range(3):
        flow.advance()  # -> estimation
    flow.submit_estimate(2.0e7)
    flow.submit_estimate(2.0e6)
    flow.submit_estimate(500)
    ests = flow.estimates
    assert [e.segment for e in ests] == SEGMENTS
    assert [e.value for e in ests] == [2.0e7, 2.0e6, 500.0]


def test_context_is_coach_persona_and_scoped_to_step():
    flow = GuessFlow(_guess())
    for _ in range(3):
        flow.advance()  # estimation
    blob = "\n".join(m["content"] for m in flow.context())
    assert "case coach" in blob.lower()  # coach persona system prompt
    assert "Estimating segment: delhi_pop" in blob
    assert "Estimate the number of petrol pumps in Delhi." in blob
    # ground truth (segment values / answer range) is not handed to the coach
    assert "answer_range" not in blob


def test_empty_tree_rejected():
    guess = _guess()
    guess.approach.tree = []
    with pytest.raises(ValueError):
        GuessFlow(guess)
