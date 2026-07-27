"""Deterministic math checker for case checkpoints (ADR-3, T-023).

Parses numbers from free-text user turns (spec: docs/decisions.md G-4) and
compares them against a checkpoint's expected value within tolerance, flagging a
known-wrong `common_errors` value when the candidate lands on one. The LLM is
never asked to verify arithmetic; it only communicates these verdicts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.content_models import Guesstimate, MathCheckpoint, TreeSegment
from app.engine.guess_flow import SegmentEstimate

# Scale suffixes -> multiplier. '%' handled as 0.01. Bare m/b excluded on purpose.
_SCALES = {
    "%": 0.01,
    "k": 1e3,
    "thousand": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "million": 1e6,
    "millions": 1e6,
    "mn": 1e6,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "billion": 1e9,
    "billions": 1e9,
    "bn": 1e9,
}

_CURRENCY = re.compile(r"(?i)\b(?:rs\.?|inr)\b|[₹$]")
_NUMBER = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(%|[A-Za-z]+)?")


def parse_numbers(text: str) -> list[float]:
    """Extract every numeric value from a turn, applying scale suffixes."""
    text = _CURRENCY.sub(" ", text)
    out: list[float] = []
    for m in _NUMBER.finditer(text):
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        value *= _SCALES.get(suffix, 1.0)  # unknown trailing word -> factor 1
        out.append(value)
    return out


@dataclass(frozen=True)
class CheckResult:
    matched_expected: bool
    matched_value: float | None  # the parsed number that hit the expected value
    common_error: str | None  # note of the matched known-wrong value, if any
    parsed: list[float]


def check_checkpoint(cp: MathCheckpoint, text: str) -> CheckResult:
    nums = parse_numbers(text)

    for n in nums:
        if abs(n - cp.expected_value) <= cp.tolerance:
            return CheckResult(True, n, None, nums)

    for ce in cp.common_errors:
        if ce.value is None:
            continue
        for n in nums:
            if abs(n - ce.value) <= cp.tolerance:
                return CheckResult(False, None, ce.note, nums)

    return CheckResult(False, None, None, nums)


# --- Guesstimate segment checks (T-024) --------------------------------------


@dataclass(frozen=True)
class SegmentCheck:
    segment: str
    user_value: float
    expected: float
    ok: bool


@dataclass(frozen=True)
class RangeCheck:
    value: float
    low: float
    high: float
    in_range: bool


def check_segment(segment: TreeSegment, user_value: float) -> SegmentCheck:
    """Judge a user's segment estimate against the tree value. Tolerance is
    relative (a fraction of the expected value); see docs/decisions.md."""
    expected = segment.value
    band = abs(segment.tolerance * expected)
    ok = abs(user_value - expected) <= band + 1e-9
    return SegmentCheck(segment.segment, user_value, expected, ok)


def check_estimates(
    guess: Guesstimate, estimates: Sequence[SegmentEstimate]
) -> list[SegmentCheck]:
    tree = {s.segment: s for s in guess.approach.tree}
    return [check_segment(tree[e.segment], e.value) for e in estimates]


def check_final(guess: Guesstimate, final_value: float) -> RangeCheck:
    r = guess.answer_range
    return RangeCheck(final_value, r.low, r.high, r.low <= final_value <= r.high)
