import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import load_config
from app.db.store import Store
from app.engine.content_models import Case
from app.engine.scoring import (
    CASE_DIMENSIONS,
    DimensionScore,
    Scorecard,
    ScoringError,
    apply_hint_penalty,
    assemble_feedback,
    build_messages,
    call_tokens,
    persist_scorecard,
    reveal_model_answer,
    score_case,
    study_next,
)

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"


def _case() -> Case:
    return Case.model_validate(
        json.loads((FIXT / "cases" / "case-cement-profitability.json").read_text())
    )


def _config():
    return load_config()


def _long_transcript(n=300):
    turns = []
    for i in range(n):
        turns.append(
            {"role": "user", "text": f"my point number {i} about the costs and revenue"}
        )
        turns.append({"role": "assistant", "text": f"interviewer reply {i}"})
    return turns


def _scores_json(dims=CASE_DIMENSIONS):
    return json.dumps(
        {
            "scores": {
                d: {"score": 4, "evidence": [f"{d} quote a", f"{d} quote b"]}
                for d in dims
            }
        }
    )


def _fake_chat(text_fn, ratelimit=None):
    """Returns a stream yielding text_fn() with an optional telemetry record."""

    class Stream:
        record = SimpleNamespace(ratelimit=ratelimit or {})

        def __iter__(self):
            yield text_fn()

    return lambda messages: Stream()


def test_per_call_token_ceiling_respected():
    case, cfg = _case(), _config()
    turns = _long_transcript(300)
    for group in [["structure", "math"], ["judgment", "communication"], ["synthesis"]]:
        messages = build_messages(case, group, turns, cfg.scoring.max_chunk_tokens)
        assert call_tokens(messages) <= cfg.scoring.max_chunk_tokens


def test_scorecard_assembly_all_dimensions():
    card = score_case(
        _case(), _long_transcript(10), _fake_chat(_scores_json), config=_config()
    )
    assert [s.dimension for s in card.scores] == CASE_DIMENSIONS
    assert all(1 <= s.score <= 5 for s in card.scores)
    assert card.average == 4.0
    assert len(card.evidence_quotes) >= 3  # verbatim user quotes


def test_retry_after_honored_between_chunks():
    slept = []
    chat = _fake_chat(_scores_json, ratelimit={"retry-after": "2"})
    score_case(
        _case(),
        _long_transcript(5),
        chat,
        config=_config(),
        sleep=lambda s: slept.append(s),
    )
    # 3 groups -> waits between them only: 2 sleeps of 2s
    assert slept == [2.0, 2.0]


def test_bad_json_recovers_on_reformat_retry():
    calls = {"n": 0}

    def text_fn():
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else _scores_json()

    card = score_case(
        _case(), _long_transcript(5), _fake_chat(text_fn), config=_config()
    )
    assert len(card.scores) == 5
    assert calls["n"] > 3  # first chunk needed a retry


def test_persistent_bad_json_fails_chunk_visibly():
    with pytest.raises(ScoringError):
        score_case(
            _case(),
            _long_transcript(5),
            _fake_chat(lambda: "garbage"),
            config=_config(),
        )


def test_reveal_is_case_file_content_verbatim():
    case = _case()
    ma = case.model_answer
    reveal = reveal_model_answer(case)
    # every model-answer field appears verbatim, none paraphrased (ADR-1)
    assert ma.framework in reveal
    assert ma.recommendation in reveal
    assert ma.walkthrough in reveal
    for insight in ma.key_insights:
        assert insight in reveal


def test_hint_penalty_docks_every_dimension_and_floors_at_one():
    card = Scorecard(
        [DimensionScore("structure", 4, ["q"]), DimensionScore("math", 1, [])]
    )
    docked = apply_hint_penalty(card, hints_used=2, cost=1.0)  # -2 points each
    assert docked.hints_used == 2
    by_dim = {s.dimension: s.score for s in docked.scores}
    assert by_dim["structure"] == 2  # 4 - 2
    assert by_dim["math"] == 1  # 1 - 2 floored at 1


def test_no_hints_leaves_scores_unchanged():
    card = Scorecard([DimensionScore("structure", 4, ["q"])])
    same = apply_hint_penalty(card, hints_used=0, cost=1.0)
    assert same.scores[0].score == 4 and same.hints_used == 0


def test_feedback_mentions_hints_used():
    card = Scorecard(
        [DimensionScore(d, 3, ["q"]) for d in CASE_DIMENSIONS], hints_used=1
    )
    assert "1 hint(s) used" in assemble_feedback(_case(), card)


def test_feedback_references_rubric_anchors():
    case = _case()
    # score each dimension 3 so the anchor at level 3 is the one quoted
    card = Scorecard([DimensionScore(d, 3, ["q"]) for d in CASE_DIMENSIONS])
    fb = assemble_feedback(case, card)
    for dim in CASE_DIMENSIONS:
        anchor = getattr(case.rubric, dim).anchors[3]
        assert anchor in fb  # the achieved-level anchor phrase is present
        assert f"{dim}: 3/5" in fb


def test_feedback_uses_nearest_anchor_when_level_undefined():
    case = _case()  # structure anchors are defined at 1, 3, 5 only
    card = Scorecard([DimensionScore("structure", 4, ["q"])])
    fb = assemble_feedback(case, card)
    assert case.rubric.structure.anchors[3] in fb  # nearest at-or-below


def test_study_next_returns_lowest_scoring_dimensions():
    card = Scorecard(
        [
            DimensionScore("structure", 4, []),
            DimensionScore("math", 2, []),
            DimensionScore("judgment", 2, []),
            DimensionScore("communication", 5, []),
            DimensionScore("synthesis", 3, []),
        ]
    )
    assert study_next(card) == ["math", "judgment"]


def test_persist_scorecard_round_trips():
    store = Store(":memory:")
    sid = store.create_session("case-cement-profitability", "case", "standard")
    card = score_case(
        _case(), _long_transcript(5), _fake_chat(_scores_json), config=_config()
    )
    persist_scorecard(store, sid, card)
    rows = store.get_scorecards(sid)
    assert {r["dimension"] for r in rows} == set(CASE_DIMENSIONS)
    assert all(r["score"] == 4 for r in rows)
    store.close()
