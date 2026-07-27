"""Mental-math sprints (T-063): generation ranges, grading tolerance, sprint
scoring, and storage. All offline; rng is injected so runs are reproducible."""

import random

import pytest

from app.db.store import Store
from app.engine.content_models import Benchmarks
from app.engine.drills import (
    KINDS,
    Drill,
    flashcard_drills,
    generate,
    generate_sprint,
    grade,
    record_sprint,
    run_sprint,
    score_sprint,
)


@pytest.mark.parametrize("kind", KINDS)
def test_generated_drill_answer_is_self_consistent(kind):
    # A generated drill's stated answer must actually solve its own prompt: grade
    # the exact answer and it passes for every kind, over many seeds.
    for seed in range(50):
        d = generate(kind, random.Random(seed))
        assert d.kind == kind
        assert grade(d, d.answer)


def test_percent_and_division_are_exact():
    d = generate("percent", random.Random(1))
    assert d.tolerance == 0.0
    assert not grade(d, d.answer + 1)  # exact: off-by-one fails


def test_growth_allows_rounding_slack():
    d = generate("growth", random.Random(3))
    assert grade(d, d.answer * 1.01)  # within 2%
    assert not grade(d, d.answer * 1.5)


def test_generate_sprint_length_and_kinds():
    drills = generate_sprint(6, random.Random(0), kinds=("percent",))
    assert len(drills) == 6
    assert {d.kind for d in drills} == {"percent"}


def test_score_sprint_counts_correct_and_labels_kind():
    drills = [
        Drill("percent", "10% of 200?", 20, 0.0),
        Drill("percent", "50% of 40?", 20, 0.0),
    ]
    r = score_sprint(drills, [20, 999], elapsed_ms=1234.0)
    assert (r.total, r.correct, r.kind) == (2, 1, "percent")
    assert r.accuracy == 0.5
    assert r.elapsed_ms == 1234.0


def test_mixed_kinds_label():
    drills = [Drill("percent", "", 1, 0.0), Drill("division", "", 2, 0.0)]
    assert score_sprint(drills, [None, None]).kind == "mixed"


def test_record_sprint_persists_and_summarizes():
    store = Store(":memory:")
    drills = [Drill("percent", "", 20, 0.0), Drill("percent", "", 20, 0.0)]
    record_sprint(store, score_sprint(drills, [20, 999]))
    assert store.drill_summary() == [
        {"kind": "percent", "attempts": 2, "correct": 1, "accuracy": 0.5}
    ]
    store.close()


def _benchmarks():
    return Benchmarks.model_validate(
        {
            "india_population": {"value": 1.4e9, "unit": "people", "as_of": 2026},
            "delhi_population": {"value": 2.0e7, "unit": "people", "as_of": 2026},
        }
    )


def test_flashcards_sourced_from_benchmarks():
    cards = flashcard_drills(_benchmarks())
    assert len(cards) == 2
    by_key = {c.answer: c for c in cards}
    india = by_key[1.4e9]
    assert india.kind == "flashcard"
    assert "india population" in india.prompt and "(people)" in india.prompt
    assert grade(india, 1.5e9)  # within 20% recalls
    assert not grade(india, 2.0e9)  # off by >40% fails


def test_flashcards_grade_through_the_drill_pipeline():
    cards = flashcard_drills(_benchmarks())
    answers = [c.answer for c in cards]
    assert score_sprint(cards, answers).correct == 2


def test_run_sprint_reads_answers_and_stores():
    store = Store(":memory:")
    drills = generate_sprint(3, random.Random(7), kinds=("percent",))
    # answer the first two correctly, third wrong; feed via a scripted reader
    answers = iter([str(drills[0].answer), str(drills[1].answer), "0"])
    ticks = iter([0.0, 2.0])  # 2s elapsed
    result = run_sprint(
        store,
        read=lambda: next(answers),
        emit=lambda t: None,
        n=3,
        kinds=("percent",),
        rng=random.Random(7),  # same seed -> same drills as above
        clock=lambda: next(ticks),
    )
    assert (result.total, result.correct) == (3, 2)
    assert result.elapsed_ms == 2000.0
    assert store.drill_summary()[0]["correct"] == 2
    store.close()
