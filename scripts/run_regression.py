#!/usr/bin/env python3
"""Prompt regression suite (T-070, 07_PROMPTS §6).

Runs canned user inputs through each persona against the current templates and
flags the five violation classes from §6: leaked solution/rubric in interviewer
output, invented numbers (not in the injected content slice), broken character
(meta-commentary / persona drift), a coach revealing the model approach before an
attempt, and scoring output that fails strict JSON parse.

The detectors are pure keyword/pattern checks (§6: do not over-engineer) and are
unit-tested against canned bad outputs. The live run touches the provider, so it
is gated behind --run and prints a daily-budget warning first.

    python scripts/run_regression.py            # dry run: list inputs + call count
    python scripts/run_regression.py --run      # call the live provider
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
INPUTS_DIR = ROOT / "tests" / "regression" / "inputs"
PERSONAS = ("interviewer", "coach", "tutor")


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str


# --- detectors (pure, unit-tested) ------------------------------------------

_META = re.compile(
    r"\b(as an ai|as a large language model|language model|i am an ai|"
    r"i'm an ai|as an assistant|i cannot help|being an ai)\b",
    re.I,
)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_HEADER = re.compile(r"(?m)^#{1,6}\s")


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUM.findall(text)}


def broken_character(output: str) -> list[Violation]:
    v = [Violation("broken-character", m) for m in _META.findall(output)]
    if _HEADER.search(output):
        v.append(Violation("broken-character", "markdown header"))
    return v


def invented_numbers(output: str, content_slice: str) -> list[Violation]:
    allowed = _numbers(content_slice)
    return [
        Violation("invented-number", n) for n in _numbers(output) if n not in allowed
    ]


def leaked_solution(output: str, forbidden: list[str]) -> list[Violation]:
    low = output.lower()
    return [
        Violation("leaked-solution", p) for p in forbidden if p and p.lower() in low
    ]


def coach_reveal_before_attempt(output: str, model_approach: str) -> list[Violation]:
    """Flag if a distinctive slice of the model approach appears verbatim before
    the candidate has attempted (the coach must wait for an attempt)."""
    probe = " ".join(model_approach.split())[:40]
    if probe and probe.lower() in " ".join(output.split()).lower():
        return [Violation("coach-early-reveal", probe)]
    return []


def bad_scoring_json(output: str) -> list[Violation]:
    try:
        json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return [Violation("bad-scoring-json", output[:60])]
    return []


def forbidden_from_case(case) -> list[str]:
    """Distinctive solution/rubric phrases the interviewer must never leak."""
    ma = case.model_answer
    phrases = [ma.framework, ma.recommendation, *ma.key_insights]
    return [p for p in phrases if p and len(p) > 8]


# --- inputs -----------------------------------------------------------------


def load_inputs(persona: str) -> list[str]:
    path = INPUTS_DIR / f"{persona}.txt"
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]


# --- live run (network; gated) ----------------------------------------------


def _fixture_case():
    from app.engine.content_models import Case

    p = ROOT / "tests/fixtures/content/valid/cases/case-cement-profitability.json"
    return Case.model_validate(json.loads(p.read_text()))


def _run_live(chat) -> int:  # pragma: no cover - network path, eyeballed by hand
    from app.llm.templates import (
        build_coach_context,
        build_interviewer_context,
        interviewer_slice,
    )

    case = _fixture_case()
    forbidden = forbidden_from_case(case)
    phase = case.phases[0].name
    slice_ = interviewer_slice(case, phase_name=phase)
    total = 0
    for text in load_inputs("interviewer"):
        msgs = build_interviewer_context(
            case, phase_name=phase, transcript=[{"role": "user", "content": text}]
        )
        out = "".join(chat(msgs))
        found = (
            leaked_solution(out, forbidden)
            + invented_numbers(out, slice_)
            + broken_character(out)
        )
        total += len(found)
        _report("interviewer", text, found)
    for text in load_inputs("coach"):
        msgs = build_coach_context(
            case,
            phase_name=phase,
            transcript=[{"role": "user", "content": text}],
            reveal_model_approach=False,
        )
        out = "".join(chat(msgs))
        approach = case.phases[0].coaching.model_approach_for_phase
        found = coach_reveal_before_attempt(out, approach) + broken_character(out)
        total += len(found)
        _report("coach", text, found)
    return total


def _report(  # pragma: no cover
    persona: str, text: str, found: list[Violation]
) -> None:
    tag = "OK  " if not found else "FAIL"
    print(f"{tag} [{persona}] {text[:50]}")
    for v in found:
        print(f"       ! {v.kind}: {v.detail}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Prompt regression suite (T-070)")
    ap.add_argument("--run", action="store_true", help="call the live provider")
    args = ap.parse_args(argv[1:])

    counts = {p: len(load_inputs(p)) for p in PERSONAS}
    calls = counts["interviewer"] + counts["coach"]  # tutor is eyeballed separately
    for p in PERSONAS:
        print(f"{p}: {counts[p]} canned inputs")

    if not args.run:
        print(f"\nDry run. Pass --run to make {calls} live calls.")
        return 0

    print(f"\n⚠ Budget: this makes {calls} live requests against your daily quota.")
    from app.config import load_config
    from app.providers.router import Router

    violations = _run_live(Router(load_config()).chat)
    print(f"\n{violations} violation(s) flagged — eyeball the FAIL lines above.")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
