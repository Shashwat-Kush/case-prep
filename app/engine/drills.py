"""Mental-math sprints (T-063, Phase 5): LLM-free generated drills — percentages,
breakevens, growth, and big-number division — with deterministic grading. The rng
is injected so tests are reproducible; nothing here touches the network, so drills
run fully offline. Results are stored via the store and summarized for the
progress view.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

KINDS = ("percent", "breakeven", "growth", "division")


@dataclass(frozen=True)
class Drill:
    kind: str
    prompt: str
    answer: float
    tolerance: float  # relative fraction; 0.0 means exact


def _percent(rng: random.Random) -> Drill:
    pct = rng.choice([5, 10, 15, 20, 25, 30, 40, 50, 75])
    base = rng.randint(2, 99) * 100  # clean hundreds -> clean answer
    return Drill("percent", f"{pct}% of {base:,}?", base * pct / 100, 0.0)


def _breakeven(rng: random.Random) -> Drill:
    margin = rng.randint(5, 50)  # price - unit cost
    unit_cost = rng.randint(10, 200)
    units = rng.randint(100, 5000)
    fixed = units * margin
    price = unit_cost + margin
    return Drill(
        "breakeven",
        f"Fixed cost {fixed:,}, price {price}, unit cost {unit_cost}. "
        "Break-even units?",
        units,
        0.0,
    )


def _growth(rng: random.Random) -> Drill:
    value = rng.randint(1, 20) * 100
    rate = rng.choice([10, 20, 25, 50])
    years = rng.randint(2, 4)
    final = value * (1 + rate / 100) ** years
    return Drill(
        "growth",
        f"{value:,} growing {rate}%/yr for {years} years. Final value?",
        final,
        0.02,  # compounding is messy; allow 2% for rounding
    )


def _division(rng: random.Random) -> Drill:
    divisor = rng.randint(2, 99)
    quotient = rng.randint(100, 9999)
    dividend = divisor * quotient
    return Drill("division", f"{dividend:,} ÷ {divisor}?", quotient, 0.0)


_GENERATORS = {
    "percent": _percent,
    "breakeven": _breakeven,
    "growth": _growth,
    "division": _division,
}


def generate(kind: str, rng: random.Random) -> Drill:
    return _GENERATORS[kind](rng)


def generate_sprint(
    n: int, rng: random.Random, kinds: tuple[str, ...] = KINDS
) -> list[Drill]:
    return [generate(rng.choice(kinds), rng) for _ in range(n)]


def grade(drill: Drill, answer: float) -> bool:
    slack = max(drill.tolerance * abs(drill.answer), 1e-6)
    return abs(answer - drill.answer) <= slack


# --- benchmark flashcards (T-064) -------------------------------------------
# Cards are sourced live from benchmarks.json — recall the value for a fact. They
# reuse the whole drill pipeline (grade/score/record) as kind "flashcard"; the
# tolerance is loose because benchmarks are recalled estimates.

_FLASHCARD_TOLERANCE = 0.2  # within 20% counts as recalled


def flashcard_drills(benchmarks, rng: random.Random | None = None) -> list[Drill]:
    items = list(benchmarks.root.items())
    if rng is not None:
        rng.shuffle(items)
    return [
        Drill(
            "flashcard",
            f"{key.replace('_', ' ')}? ({bm.unit})",
            bm.value,
            _FLASHCARD_TOLERANCE,
        )
        for key, bm in items
    ]


@dataclass(frozen=True)
class SprintResult:
    kind: str  # a single kind, or "mixed"
    total: int
    correct: int
    elapsed_ms: float | None

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def score_sprint(
    drills: list[Drill], answers: list[float | None], elapsed_ms: float | None = None
) -> SprintResult:
    pairs = zip(drills, answers, strict=False)
    correct = sum(1 for d, a in pairs if a is not None and grade(d, a))
    kinds = {d.kind for d in drills}
    label = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    return SprintResult(label, len(drills), correct, elapsed_ms)


def record_sprint(store, result: SprintResult) -> int:
    return store.add_drill_result(
        result.kind, result.total, result.correct, result.elapsed_ms
    )


def run_sprint(
    store, read, emit, *, n=5, kinds=KINDS, rng=None, clock=None
) -> SprintResult:
    """Terminal sprint (T-063 CLI hook): pose n drills, read typed answers, grade,
    store, and return the result. `read`/`emit`/`rng`/`clock` are seams for tests."""
    import time

    rng = rng or random.Random()
    clock = clock or time.monotonic
    drills = generate_sprint(n, rng, kinds)
    answers: list[float | None] = []
    start = clock()
    for i, d in enumerate(drills, 1):
        emit(f"{i}. {d.prompt} ")
        try:
            answers.append(float(read().strip().replace(",", "")))
        except ValueError:
            answers.append(None)  # unparseable -> counts as wrong
    elapsed_ms = (clock() - start) * 1000
    result = score_sprint(drills, answers, elapsed_ms)
    record_sprint(store, result)
    emit(f"\n{result.correct}/{result.total} correct in {elapsed_ms / 1000:.1f}s\n")
    return result
