"""Chunked scoring orchestrator (ADR-6, T-025).

The full transcript can exceed per-minute token caps in one call, so scoring runs
as 2-3 sequential calls, one per rubric group. Each call carries only that group's
rubric anchors plus a transcript trimmed to the configured per-call token ceiling;
retry-after is honored between chunks. Output is strict JSON (07_PROMPTS §5):
one reformat retry, then the chunk fails visibly.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.config import Config
from app.engine.content_models import Case
from app.llm.templates import Message

# The five case rubric dimensions (CaseRubric), split into groups of two so
# scoring is 2-3 calls (ADR-6): [structure, math] [judgment, communication] [synthesis].
CASE_DIMENSIONS = ["structure", "math", "judgment", "communication", "synthesis"]

Chat = Callable[[list[Message]], Iterable[str]]

_SCORING_SYSTEM = """You are a scoring engine for case-interview practice. Score \
ONLY these dimensions: {dims}. Use the rubric anchors below. For each dimension \
give an integer score from 1 to 5 and 2-3 short VERBATIM quotes of the candidate \
(the "user" turns) as evidence.

Rubric anchors:
{anchors}

Output JSON only, no markdown fences, exactly this shape:
{{"scores": {{"<dimension>": {{"score": <1-5>, "evidence": ["<verbatim quote>"]}}}}}}"""

_REMINDER: Message = {
    "role": "system",
    "content": "Your last reply was not valid JSON in the required shape. "
    "Reply with JSON only, no prose, no fences.",
}


class ScoringError(Exception):
    """A chunk failed to produce valid JSON even after one reformat retry."""


@dataclass(frozen=True)
class DimensionScore:
    dimension: str
    score: int
    evidence: list[str]


@dataclass(frozen=True)
class Scorecard:
    scores: list[DimensionScore]

    @property
    def average(self) -> float:
        return (
            sum(s.score for s in self.scores) / len(self.scores) if self.scores else 0.0
        )

    @property
    def evidence_quotes(self) -> list[str]:
        return [q for s in self.scores for q in s.evidence]


def estimate_tokens(text: str) -> int:
    """Cheap proxy: ~4 chars per token (no tokenizer dependency, YAGNI)."""
    return len(text) // 4


def call_tokens(messages: Sequence[Message]) -> int:
    return sum(estimate_tokens(m["content"]) for m in messages)


def _groups(dims: list[str], size: int = 2) -> list[list[str]]:
    return [dims[i : i + size] for i in range(0, len(dims), size)]


def _anchor_text(case: Case, group: list[str]) -> str:
    lines = []
    for dim in group:
        anchors = getattr(case.rubric, dim).anchors
        rendered = "; ".join(f"{k}={v}" for k, v in sorted(anchors.items()))
        lines.append(f"- {dim}: {rendered}")
    return "\n".join(lines)


def _render(turns: Sequence[Message]) -> str:
    return "\n".join(f"{t['role']}: {t['text']}" for t in turns)


def _fit_transcript(turns: Sequence[Message], budget_chars: int) -> list[Message]:
    """Keep the most recent turns that fit the budget (at least one)."""
    kept: list[Message] = []
    total = 0
    for t in reversed(turns):
        line = len(f"{t['role']}: {t['text']}\n")
        if total + line > budget_chars and kept:
            break
        kept.append(t)
        total += line
    return list(reversed(kept))


def build_messages(
    case: Case, group: list[str], turns: Sequence[Message], max_tokens: int
) -> list[Message]:
    system = _SCORING_SYSTEM.format(
        dims=", ".join(group), anchors=_anchor_text(case, group)
    )
    budget_chars = max(max_tokens * 4 - len(system) - 200, 0)
    kept = _fit_transcript(turns, budget_chars)
    user = "Transcript:\n" + _render(kept) + "\n\nReturn the JSON now."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _collect(chat: Chat, messages: list[Message]):
    stream = chat(messages)
    text = "".join(stream)
    return text, getattr(stream, "record", None)


def _parse(text: str, group: list[str]) -> dict[str, DimensionScore]:
    scores = json.loads(text)["scores"]
    out: dict[str, DimensionScore] = {}
    for dim in group:
        d = scores[dim]
        out[dim] = DimensionScore(dim, int(d["score"]), list(d.get("evidence", [])))
    return out


def _retry_after(record) -> float:
    ratelimit = getattr(record, "ratelimit", {}) or {}
    try:
        return float(ratelimit.get("retry-after") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def score_case(
    case: Case,
    transcript: Sequence[Message],
    chat: Chat,
    *,
    config: Config,
    sleep: Callable[[float], None] = time.sleep,
) -> Scorecard:
    max_tokens = config.scoring.max_chunk_tokens
    groups = _groups(CASE_DIMENSIONS)
    results: dict[str, DimensionScore] = {}

    for i, group in enumerate(groups):
        messages = build_messages(case, group, transcript, max_tokens)
        text, record = _collect(chat, messages)
        try:
            parsed = _parse(text, group)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            text, record = _collect(chat, [*messages, _REMINDER])
            try:
                parsed = _parse(text, group)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                raise ScoringError(f"scoring chunk {group} failed to parse: {e}") from e
        results.update(parsed)

        if i < len(groups) - 1:  # honor retry-after between chunks, not after the last
            wait = _retry_after(record)
            if wait:
                sleep(wait)

    return Scorecard([results[d] for d in CASE_DIMENSIONS if d in results])


def persist_scorecard(store, session_id: int, scorecard: Scorecard) -> None:
    for s in scorecard.scores:
        store.add_scorecard(
            session_id, s.dimension, s.score, evidence=" | ".join(s.evidence)
        )
