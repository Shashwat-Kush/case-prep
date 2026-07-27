"""Dashboard aggregation (T-062, Phase 5): compose the coverage map (T-060) and
ladder recommendation (T-061) with per-dimension score trends into a single JSON
payload for the home screen. Pure over the store + library; no LLM calls.

The Phase 5 exit criterion — a defensible next step after ~5 sessions — is the
`recommendation` field; `dimensions` gives the score trend and weakness flags
behind it.
"""

from __future__ import annotations

from app.config import Config
from app.engine.ladder import recommend
from app.engine.progress import build_coverage


def build_dashboard(store, library, config: Config) -> dict:
    coverage = build_coverage(store, library)
    rec = recommend(coverage, config)
    bar = config.ladder.graduation_min_avg
    sessions = store.list_sessions()

    # Per-dimension score series in session (chronological) order.
    series: dict[str, list[int]] = {}
    for s in sessions:
        for sc in store.get_scorecards(s["id"]):
            series.setdefault(sc["dimension"], []).append(sc["score"])

    dimensions = [
        {
            "dimension": dim,
            "scores": scores,
            "avg": round(sum(scores) / len(scores), 2),
            "latest": scores[-1],
            "weak": sum(scores) / len(scores) < bar,  # below the graduation bar
        }
        for dim, scores in sorted(series.items())
    ]

    return {
        "sessions": {
            "total": len(sessions),
            "completed": sum(1 for s in sessions if s["ended_at"]),
        },
        "recommendation": {"rule": rec.rule, "message": rec.message},
        "graduation_bar": bar,
        "dimensions": dimensions,
        "weaknesses": [d["dimension"] for d in dimensions if d["weak"]],
        "topics": [
            {"topic": t.topic, "attempts": t.attempts, "avg_score": t.avg_score()}
            for t in sorted(coverage.topics.values(), key=lambda t: t.topic)
        ],
        "concepts_taught": sorted(
            c.concept for c in coverage.concepts.values() if c.taught
        ),
        "drills": store.drill_summary(),  # LLM-free mental-math sprints (T-063)
    }
