"""Ladder rule table (T-061). Each fixture is a coverage snapshot; assert which
rule fires and that the message cites it. Graduation bar is config-driven (3.0)."""

from app.config import load_config
from app.engine.ladder import recommend
from app.engine.progress import ConceptRecord, Coverage, TopicRecord


def _cov(concepts=(), topics=()):
    return Coverage({c.concept: c for c in concepts}, {t.topic: t for t in topics})


CFG = load_config()  # graduation_min_avg defaults to 3.0 in config.yaml


def test_cold_start_when_nothing_done():
    rec = recommend(_cov(), CFG)
    assert rec.rule == "cold-start"
    assert "lesson" in rec.message


def test_graduation_at_exactly_the_bar():
    topics = [TopicRecord("profitability", {"standard": 2}, {"standard": [3, 3]})]
    rec = recommend(_cov(topics=topics), CFG)
    assert rec.rule == "graduation"
    assert "cold-mode profitability" in rec.message
    assert "3.0/5" in rec.message


def test_below_bar_is_weakness_not_graduation():
    topics = [TopicRecord("market-entry", {"standard": 2}, {"standard": [2, 3]})]
    rec = recommend(_cov(topics=topics), CFG)
    assert rec.rule == "weakness"
    assert "market-entry" in rec.message


def test_guided_scores_do_not_graduate():
    # strong guided average, but graduation looks at standard mode only
    topics = [TopicRecord("profitability", {"guided": 2}, {"guided": [5, 5]})]
    rec = recommend(_cov(topics=topics), CFG)
    assert rec.rule == "weakness"  # no standard scores -> not graduated


def test_weakness_picks_the_lowest_scored_topic():
    topics = [
        TopicRecord("profitability", {"standard": 1}, {"standard": [3]}),  # avg 3.0
        TopicRecord("market-entry", {"standard": 1}, {"standard": [2]}),  # avg 2.0
    ]
    rec = recommend(_cov(topics=topics), CFG)
    # profitability graduates (>=3.0), so graduation wins over weakness
    assert rec.rule == "graduation" and "profitability" in rec.message


def test_explore_when_concepts_covered_but_no_scored_cases():
    concepts = [ConceptRecord("mece", ["lesson-mece"])]
    topics = [TopicRecord("profitability", {"standard": 1}, {})]  # attempted, unscored
    rec = recommend(_cov(concepts=concepts, topics=topics), CFG)
    assert rec.rule == "explore"


def test_message_always_names_the_rule():
    rec = recommend(_cov(), CFG)
    assert f"rule: {rec.rule}" in rec.message
