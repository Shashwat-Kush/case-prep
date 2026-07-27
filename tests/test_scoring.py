import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import load_config
from app.db.store import Store
from app.engine.content_models import Case
from app.engine.scoring import (
    CASE_DIMENSIONS,
    ScoringError,
    build_messages,
    call_tokens,
    persist_scorecard,
    score_case,
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
