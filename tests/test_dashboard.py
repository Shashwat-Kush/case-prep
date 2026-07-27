"""Dashboard aggregation (T-062): a scripted ~5-session history through the store
must yield a defensible next step plus per-dimension trends and weakness flags."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import load_config
from app.db.store import Store
from app.engine.dashboard import build_dashboard

FIXED = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
CFG = load_config()  # graduation_min_avg 3.0


class FakeLibrary:
    def __init__(self, items):
        self._items = items

    def get(self, cid):
        return self._items.get(cid)


def _case(type_):
    return SimpleNamespace(meta=SimpleNamespace(type=type_))


@pytest.fixture
def store() -> Store:
    s = Store(":memory:", now=lambda: FIXED)
    yield s
    s.close()


def test_empty_history_recommends_cold_start(store: Store):
    d = build_dashboard(store, FakeLibrary({}), CFG)
    assert d["sessions"] == {"total": 0, "completed": 0}
    assert d["recommendation"]["rule"] == "cold-start"
    assert d["dimensions"] == [] and d["weaknesses"] == []


def test_dimension_trends_and_weakness_flags(store: Store):
    lib = FakeLibrary({"case-a": _case("profitability")})
    # three standard cases: structure trends up, math stays weak
    for structure, math in [(2, 2), (3, 2), (4, 3)]:
        sid = store.create_session("case-a", "case", "standard")
        store.add_scorecard(sid, "structure", structure)
        store.add_scorecard(sid, "math", math)
        store.end_session(sid)

    d = build_dashboard(store, lib, CFG)
    dims = {x["dimension"]: x for x in d["dimensions"]}
    assert dims["structure"]["scores"] == [2, 3, 4]  # chronological
    assert dims["structure"]["latest"] == 4
    assert dims["math"]["avg"] == round(7 / 3, 2)
    assert dims["math"]["weak"] is True  # 2.33 < 3.0 bar
    assert dims["structure"]["weak"] is False  # avg 3.0 is at the bar, not below
    assert d["weaknesses"] == ["math"]


def test_topics_rolled_up_with_attempts(store: Store):
    lib = FakeLibrary({"case-a": _case("profitability")})
    s1 = store.create_session("case-a", "case", "standard")
    store.add_scorecard(s1, "structure", 4)
    store.create_session("case-a", "case", "guided")
    d = build_dashboard(store, lib, CFG)
    topic = d["topics"][0]
    assert topic["topic"] == "profitability"
    assert topic["attempts"] == {"standard": 1, "guided": 1}
