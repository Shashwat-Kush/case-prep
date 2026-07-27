"""Concept coverage map (T-060). Scripted sessions into an in-memory store, a
tiny stand-in library (build_coverage only reads .get(id).meta), assert the
per-concept and per-topic-per-mode rollup that feeds the ladder."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.db.store import Store
from app.engine.progress import build_coverage

FIXED = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


class FakeLibrary:
    def __init__(self, items: dict):
        self._items = items

    def get(self, content_id: str):
        return self._items.get(content_id)


def _lesson(*concepts):
    return SimpleNamespace(meta=SimpleNamespace(concepts_taught=list(concepts)))


def _case(type_):
    return SimpleNamespace(meta=SimpleNamespace(type=type_))


@pytest.fixture
def store() -> Store:
    s = Store(":memory:", now=lambda: FIXED)
    yield s
    s.close()


def test_completed_lesson_marks_concepts_taught(store: Store):
    sid = store.create_session("lesson-profitability", "lesson")
    store.end_session(sid)
    lib = FakeLibrary({"lesson-profitability": _lesson("profitability", "mece")})

    cov = build_coverage(store, lib)
    assert cov.concept("profitability").taught
    assert cov.concept("mece").lessons_done == ["lesson-profitability"]
    assert cov.concept("unstarted").taught is False


def test_unfinished_lesson_is_not_counted(store: Store):
    store.create_session("lesson-profitability", "lesson")  # no end_session
    lib = FakeLibrary({"lesson-profitability": _lesson("profitability")})
    assert build_coverage(store, lib).concept("profitability").taught is False


def test_case_attempts_counted_per_mode_with_scores(store: Store):
    s1 = store.create_session("case-a", "case", "standard")
    store.add_scorecard(s1, "structure", 4)
    store.add_scorecard(s1, "math", 3)
    s2 = store.create_session("case-b", "case", "standard")
    store.add_scorecard(s2, "structure", 5)
    store.create_session("case-c", "case", "guided")
    lib = FakeLibrary(
        {
            "case-a": _case("profitability"),
            "case-b": _case("profitability"),
            "case-c": _case("profitability"),
        }
    )

    topic = build_coverage(store, lib).topic("profitability")
    assert topic.attempts == {"standard": 2, "guided": 1}
    assert topic.total_attempts == 3
    assert topic.scores == [4, 3, 5]
    assert topic.avg_score == 4.0


def test_missing_content_is_skipped(store: Store):
    store.create_session("deleted-case", "case", "standard")
    cov = build_coverage(store, FakeLibrary({}))
    assert cov.topics == {}
    assert cov.topic("anything").total_attempts == 0
