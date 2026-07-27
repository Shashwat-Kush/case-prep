"""Concept coverage map (T-060, Phase 5): a queryable record of which concepts
have been taught (lessons done) and which case types have been attempted per
mode, assembled from the store and the content library. Feeds ladder rules
(T-061).

Concepts come from a completed lesson's `concepts_taught`; case topics are the
case's `type`, with attempts counted per mode and scorecard scores collected so
the ladder can apply its graduation rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.store import Store
from app.engine.content_loader import ContentLibrary


@dataclass(frozen=True)
class ConceptRecord:
    concept: str
    lessons_done: list[str] = field(default_factory=list)

    @property
    def taught(self) -> bool:
        return bool(self.lessons_done)


@dataclass(frozen=True)
class TopicRecord:
    topic: str
    attempts: dict[str, int] = field(default_factory=dict)  # mode -> count
    scores: list[int] = field(default_factory=list)

    @property
    def total_attempts(self) -> int:
        return sum(self.attempts.values())

    @property
    def avg_score(self) -> float | None:
        return sum(self.scores) / len(self.scores) if self.scores else None


@dataclass(frozen=True)
class Coverage:
    concepts: dict[str, ConceptRecord]
    topics: dict[str, TopicRecord]

    def concept(self, concept_id: str) -> ConceptRecord:
        return self.concepts.get(concept_id, ConceptRecord(concept_id))

    def topic(self, topic: str) -> TopicRecord:
        return self.topics.get(topic, TopicRecord(topic))


def build_coverage(store: Store, library: ContentLibrary) -> Coverage:
    concepts: dict[str, ConceptRecord] = {}
    topics: dict[str, TopicRecord] = {}
    for s in store.list_sessions():
        content = library.get(s["content_id"])
        if content is None:  # content file removed since — skip, never crash
            continue
        if s["content_type"] == "lesson" and s["ended_at"]:
            for c in content.meta.concepts_taught:
                rec = concepts.setdefault(c, ConceptRecord(c))
                if s["content_id"] not in rec.lessons_done:
                    rec.lessons_done.append(s["content_id"])
        elif s["content_type"] == "case":
            rec = topics.setdefault(content.meta.type, TopicRecord(content.meta.type))
            mode = s["mode"] or "standard"
            rec.attempts[mode] = rec.attempts.get(mode, 0) + 1
            rec.scores.extend(sc["score"] for sc in store.get_scorecards(s["id"]))
    return Coverage(concepts, topics)
