"""Ladder rules + next-step recommendation (T-061, Phase 5).

Turns a coverage rollup (T-060) plus the config graduation bar into a single,
explainable next step. Recommendations are advisory only — nothing here locks
content; the whole library is always reachable (PRD §5, G-10). Each recommendation
names the rule that fired so the "why" is legible.

Rules, highest priority first:
  cold-start  no concepts taught and no cases attempted -> start with a lesson
  graduation  a topic's standard-mode average >= graduation_min_avg -> cold mode
  weakness    the weakest scored topic is below the bar -> keep practicing it
  explore     concepts covered but no scored cases yet -> attempt a standard case
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.engine.progress import Coverage


@dataclass(frozen=True)
class Recommendation:
    rule: str
    message: str


def recommend(coverage: Coverage, config: Config) -> Recommendation:
    bar = config.ladder.graduation_min_avg
    concepts, topics = coverage.concepts, coverage.topics

    if not any(c.taught for c in concepts.values()) and not topics:
        return Recommendation(
            "cold-start",
            "No sessions on record (rule: cold-start) — start with a foundational "
            "lesson to build concepts before your first case.",
        )

    graduated = sorted(
        (
            t
            for t in topics.values()
            if (a := t.avg_score("standard")) is not None and a >= bar
        ),
        key=lambda t: t.topic,
    )
    if graduated:
        t = graduated[0]
        return Recommendation(
            "graduation",
            f"You're averaging {t.avg_score('standard'):.1f}/5 across "
            f"{t.attempts.get('standard', 0)} standard {t.topic} case(s), at or above "
            f"the {bar:g} bar (rule: graduation) — try a cold-mode {t.topic} case.",
        )

    scored = [t for t in topics.values() if t.avg_score() is not None]
    if scored:
        t = min(scored, key=lambda t: (t.avg_score(), t.topic))
        return Recommendation(
            "weakness",
            f"Your {t.topic} average is {t.avg_score():.1f}/5, below the {bar:g} bar "
            f"(rule: weakness) — keep practicing {t.topic} cases in standard mode.",
        )

    return Recommendation(
        "explore",
        "You've covered concepts but have no scored cases yet (rule: explore) — "
        "attempt a standard case to get your first scorecard.",
    )
