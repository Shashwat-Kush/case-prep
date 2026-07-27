"""STT transcript cleanup + number confirmation (T-052).

Whisper transcribes speech to text, but spoken numbers are error-prone: the
teen/ty pairs (fifteen/fifty, thirteen/thirty, …) sound alike, and Indian scale
words (lakh, crore) mix with digits. So every number a candidate states must be
CONFIRMED before it can reach the math checker (ADR-3): `detect_numbers` surfaces
each stated number with its plausible alternatives for the user to confirm or
correct inline, and `evaluate_confirmed` is the only path from a spoken turn to
checkpoint evaluation — an unconfirmed number can never affect a checkpoint.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.content_models import MathCheckpoint
from app.engine.math_checker import _CURRENCY, CheckResult, check_values

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}  # fmt: skip
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_NUM_WORD = {**_ONES, **_TEENS, **_TENS}

# Multiplicative scales (words + the digit-suffix abbreviations parse_numbers knows).
_BIG_SCALE = {
    "hundred": 100, "thousand": 1e3, "k": 1e3, "lakh": 1e5, "lakhs": 1e5,
    "lac": 1e5, "million": 1e6, "millions": 1e6, "mn": 1e6, "crore": 1e7,
    "crores": 1e7, "cr": 1e7, "billion": 1e9, "billions": 1e9, "bn": 1e9,
}  # fmt: skip
_PERCENT = {"%", "percent", "percentage"}

# Teen<->ty homophones: hearing one, the other is always a plausible correction.
_CONFUSE = {
    "thirteen": "thirty", "fourteen": "forty", "fifteen": "fifty",
    "sixteen": "sixty", "seventeen": "seventy", "eighteen": "eighty",
    "nineteen": "ninety",
}  # fmt: skip
_CONFUSE = {**_CONFUSE, **{v: k for k, v in _CONFUSE.items()}}

_DIGIT = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?$")
_TOKEN = re.compile(r"[A-Za-z]+|[+-]?\d[\d,]*(?:\.\d+)?|%")


@dataclass(frozen=True)
class DetectedNumber:
    surface: str  # the words/digits as spoken, e.g. "fifteen crore"
    value: float  # primary parsed value
    candidates: list[float]  # plausible values (primary first); >1 when ambiguous


def _is_num_token(tok: str) -> bool:
    t = tok.lower()
    return t in _NUM_WORD or t in _BIG_SCALE or t in _PERCENT or bool(_DIGIT.match(tok))


def _phrase_value(tokens: list[str]) -> float:
    total = current = 0.0
    percent = False
    for tok in tokens:
        t = tok.lower()
        if _DIGIT.match(tok):
            current += float(tok.replace(",", ""))
        elif t in _NUM_WORD:
            current += _NUM_WORD[t]
        elif t == "hundred":
            current = (current or 1) * 100
        elif t in _BIG_SCALE:
            total += (current or 1) * _BIG_SCALE[t]
            current = 0.0
        elif t in _PERCENT:
            percent = True
    value = total + current
    return value * 0.01 if percent else value


def _candidates(tokens: list[str], value: float) -> list[float]:
    """If exactly one token is a teen/ty homophone, offer the swapped reading too."""
    confusable = [i for i, t in enumerate(tokens) if t.lower() in _CONFUSE]
    if len(confusable) != 1:
        return [value]
    i = confusable[0]
    swapped = list(tokens)
    swapped[i] = _CONFUSE[tokens[i].lower()]
    alt = _phrase_value(swapped)
    return [value] if alt == value else [value, alt]


def detect_numbers(raw: str) -> list[DetectedNumber]:
    """Every number stated in the turn, with confirmation candidates."""
    text = _CURRENCY.sub(" ", raw)
    tokens = _TOKEN.findall(text)
    out: list[DetectedNumber] = []
    i = 0
    while i < len(tokens):
        if not _is_num_token(tokens[i]):
            i += 1
            continue
        j = i
        while j < len(tokens) and _is_num_token(tokens[j]):
            j += 1
        phrase = tokens[i:j]
        value = _phrase_value(phrase)
        out.append(DetectedNumber(" ".join(phrase), value, _candidates(phrase, value)))
        i = j
    return out


def clean_transcript(raw: str) -> str:
    """Cleaned display text: currency dropped, each spoken/mixed number phrase
    collapsed to its primary digit value. The confirmation UI shows the ambiguous
    alternatives separately (detect_numbers)."""
    text = _CURRENCY.sub(" ", raw)
    tokens = _TOKEN.findall(text)
    parts: list[str] = []
    i = 0
    while i < len(tokens):
        if not _is_num_token(tokens[i]):
            parts.append(tokens[i])
            i += 1
            continue
        j = i
        while j < len(tokens) and _is_num_token(tokens[j]):
            j += 1
        parts.append(_fmt(_phrase_value(tokens[i:j])))
        i = j
    return " ".join(parts)


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def evaluate_confirmed(cp: MathCheckpoint, confirmed: Sequence[float]) -> CheckResult:
    """The ONLY path from a spoken turn to checkpoint evaluation: it takes the
    numbers the user explicitly confirmed. Detected-but-unconfirmed numbers never
    reach the math checker, so they cannot affect a checkpoint (T-052 gate)."""
    return check_values(cp, list(confirmed))
