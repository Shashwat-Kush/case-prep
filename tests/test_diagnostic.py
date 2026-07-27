import json
from pathlib import Path

import pytest

from app.config import load_config
from app.db.store import Store
from app.engine.content_loader import ContentLibrary
from app.engine.content_models import Benchmarks, Case, Guesstimate
from app.engine.scoring import CASE_DIMENSIONS, DimensionScore, Scorecard
from app.engine.session_manager import (
    DiagnosticSession,
    select_diagnostic_content,
)

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"


def _load(model, rel):
    return model.model_validate(json.loads((FIXT / rel).read_text()))


def _with_diag(item, flag: bool, new_id: str | None = None):
    """Return a copy with meta.diagnostic set (and optionally a new id)."""
    meta_update = {"diagnostic": flag}
    if new_id is not None:
        meta_update["id"] = new_id
    return item.model_copy(update={"meta": item.meta.model_copy(update=meta_update)})


def _library(*, diagnostic_case=True) -> ContentLibrary:
    bench = _load(Benchmarks, "benchmarks.json")
    case = _load(Case, "cases/case-cement-profitability.json")
    case = _with_diag(case, diagnostic_case)
    g = _load(Guesstimate, "guesstimates/guess-petrol-pumps-delhi.json")
    guesses = [
        _with_diag(g, True, "guess-b-diag"),
        _with_diag(g, True, "guess-a-diag"),
        _with_diag(g, False, "guess-c-plain"),
    ]
    return ContentLibrary(
        benchmarks=bench,
        cases={case.meta.id: case},
        guesstimates={x.meta.id: x for x in guesses},
    )


def _scorecard(score=3) -> Scorecard:
    return Scorecard([DimensionScore(d, score, ["q"]) for d in CASE_DIMENSIONS])


def _config(*, visible: bool):
    return load_config().model_copy(update={"score_visibility": visible})


def test_select_picks_diagnostic_case_and_two_guesstimates_in_id_order():
    plan = select_diagnostic_content(_library())
    assert plan.case.meta.diagnostic
    ids = [g.meta.id for g in plan.guesstimates]
    # only the 2 flagged guesstimates, id-sorted; the plain one is omitted
    assert ids == ["guess-a-diag", "guess-b-diag"]


def test_select_raises_without_diagnostic_case():
    with pytest.raises(ValueError, match="no diagnostic-flagged case"):
        select_diagnostic_content(_library(diagnostic_case=False))


def test_hidden_scores_still_store_full_scorecard():
    store = Store(":memory:")
    plan = select_diagnostic_content(_library())
    diag = DiagnosticSession(store, plan, config=_config(visible=False))
    shown = diag.record_scorecard(_scorecard())
    assert shown is None  # nothing to display while hidden
    rows = store.get_scorecards(diag.session_id)
    assert {r["dimension"] for r in rows} == set(CASE_DIMENSIONS)  # stored in full
    store.close()


def test_visibility_flag_flips_display_but_storage_is_unconditional():
    store = Store(":memory:")
    plan = select_diagnostic_content(_library())
    diag = DiagnosticSession(store, plan, config=_config(visible=True))
    shown = diag.record_scorecard(_scorecard(4))
    assert shown is not None and shown.average == 4.0  # displayed when visible
    assert len(store.get_scorecards(diag.session_id)) == len(CASE_DIMENSIONS)
    store.close()


def test_finishing_seeds_global_ladder_state():
    store = Store(":memory:")
    plan = select_diagnostic_content(_library())
    diag = DiagnosticSession(store, plan, config=_config(visible=False))
    diag.seed_ladder(3.4)
    diag.end()
    ladder = store.get_ladder("global")
    assert ladder is not None
    assert ladder["level"] == 0 and ladder["avg_score"] == 3.4
    assert store.get_session(diag.session_id)["content_type"] == "diagnostic"
    assert store.get_session(diag.session_id)["ended_at"] is not None
    store.close()
