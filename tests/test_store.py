from datetime import UTC, datetime

import pytest

from app.db.store import Store

FIXED = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def store() -> Store:
    s = Store(":memory:", now=lambda: FIXED)
    yield s
    s.close()


def test_session_round_trip(store: Store):
    sid = store.create_session("case-brewbar-diagnostic", "case", "standard")
    row = store.get_session(sid)
    assert row["content_id"] == "case-brewbar-diagnostic"
    assert row["content_type"] == "case"
    assert row["mode"] == "standard"
    assert row["started_at"] == FIXED.isoformat()
    assert row["ended_at"] is None
    store.end_session(sid)
    assert store.get_session(sid)["ended_at"] == FIXED.isoformat()


def test_turn_carries_all_fields(store: Store):
    sid = store.create_session("case-x", "case")
    store.add_turn(sid, "user", "why did profit fall?", phase="analysis")
    store.add_turn(
        sid,
        "assistant",
        "Let's look at costs.",
        phase="analysis",
        provider="groq",
        latency_ms=420.5,
    )
    turns = store.get_turns(sid)
    assert [t["role"] for t in turns] == ["user", "assistant"]  # ordered by id
    a = turns[1]
    assert a["text"] == "Let's look at costs."
    assert a["ts"] == FIXED.isoformat()
    assert a["phase"] == "analysis"
    assert a["provider"] == "groq"
    assert a["latency_ms"] == 420.5


def test_scorecards_round_trip(store: Store):
    sid = store.create_session("case-x", "case")
    store.add_scorecard(sid, "structure", 4, evidence="clean MECE tree")
    store.add_scorecard(sid, "math", 3)
    cards = store.get_scorecards(sid)
    assert {(c["dimension"], c["score"]) for c in cards} == {
        ("structure", 4),
        ("math", 3),
    }
    assert cards[0]["evidence"] == "clean MECE tree"


def test_concept_coverage_round_trip(store: Store):
    sid = store.create_session("lesson-profitability", "lesson")
    store.add_concept_coverage(sid, "profit-tree", score=5)
    store.add_concept_coverage(sid, "revenue-cost-decomposition")
    cov = store.get_concept_coverage(sid)
    assert [c["concept_id"] for c in cov] == [
        "profit-tree",
        "revenue-cost-decomposition",
    ]
    assert cov[0]["score"] == 5
    assert cov[1]["score"] is None


def test_ladder_upsert(store: Store):
    store.upsert_ladder("case:profitability", 1, 3.4)
    assert store.get_ladder("case:profitability")["level"] == 1
    store.upsert_ladder("case:profitability", 2, 3.8)  # same key -> update
    row = store.get_ladder("case:profitability")
    assert row["level"] == 2 and row["avg_score"] == 3.8


def test_session_with_missing_content_id_still_readable(store: Store):
    # content file for this id may never exist or was deleted; reads must not crash
    sid = store.create_session("case-deleted-yesterday", "case", "guided")
    store.add_turn(sid, "user", "hello", phase="opening")
    assert store.get_session(sid)["content_id"] == "case-deleted-yesterday"
    assert len(store.get_turns(sid)) == 1


def test_turns_cascade_delete(store: Store):
    sid = store.create_session("case-x", "case")
    store.add_turn(sid, "user", "hi")
    store._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    store._conn.commit()
    assert store.get_turns(sid) == []  # ON DELETE CASCADE removed the turns
