"""Prompt template loading and per-call context assembly (07_PROMPTS §3-4).

Prompt files live in templates/ and are code (07_PROMPTS intro). The hard
exclusions (§4) are enforced *by construction*: interviewer_slice reads only
whitelisted case fields, so there is no code path from model_answer, rubric,
coaching, so_what, or locked exhibits into the interviewer context. Prompt-level
instructions are a second layer only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from string import Template

from app.engine.content_models import Case, Lesson

TEMPLATES_DIR = Path(__file__).parent / "templates"

Message = dict[str, str]


def load_template(name: str) -> str:
    return (TEMPLATES_DIR / f"{name}.md").read_text()


def render(name: str, /, **variables: str) -> str:
    """Load a template and substitute $variables (strict: missing ones raise)."""
    return Template(load_template(name)).substitute(variables)


def _phase(case: Case, phase_name: str):
    for p in case.phases:
        if p.name == phase_name:
            return p
    raise KeyError(f"phase not in case {case.meta.id!r}: {phase_name!r}")


def interviewer_slice(
    case: Case, *, phase_name: str, unlocked_exhibit_ids: Sequence[str] = ()
) -> str:
    """Interviewer-visible content only. Deliberately reads no solution fields
    (model_answer, rubric, coaching, so_what, expected_value) — that omission is
    the §4 exclusion enforcement."""
    phase = _phase(case, phase_name)
    parts = [f"Case prompt: {case.prompt}"]
    if case.facts:
        parts.append(f"Facts available: {json.dumps(case.facts)}")
    if case.clarifying:
        parts.append("Clarifying answers to give only when asked:")
        parts += [f"- {c.question_pattern}: {c.answer}" for c in case.clarifying]
    parts.append(f"Current phase: {phase.name}")
    parts.append(f"Your instructions this phase: {phase.interviewer_instructions}")
    unlocked = set(unlocked_exhibit_ids)
    for e in case.exhibits:
        if e.id in unlocked:  # title + data only; so_what stays out
            parts.append(f"Exhibit {e.id} ({e.title}): {json.dumps(e.data)}")
    return "\n".join(parts)


def coach_slice(
    case: Case,
    *,
    phase_name: str,
    unlocked_exhibit_ids: Sequence[str] = (),
    reveal_model_approach: bool = True,
) -> str:
    """Coach-visible content: adds the current phase's coaching block and
    unlocked-exhibit ground truth. Still no full model_answer (revealed only at
    the case-file reveal point, §4). When reveal_model_approach is False the
    phase's model approach is withheld from the context entirely, so the guided
    explain->attempt->reveal order is enforced by construction (T-018)."""
    phase = _phase(case, phase_name)
    parts = [f"Case prompt: {case.prompt}"]
    if case.facts:
        parts.append(f"Facts: {json.dumps(case.facts)}")
    parts.append(f"Current phase: {phase.name}")
    parts.append(f"Interviewer instructions: {phase.interviewer_instructions}")
    if phase.coaching:
        parts.append(f"What a strong candidate does: {phase.coaching.explain}")
        if reveal_model_approach:
            parts.append(
                "Model approach to reveal now: "
                f"{phase.coaching.model_approach_for_phase}"
            )
        else:
            parts.append(
                "Do not reveal the model approach yet; "
                "invite the candidate to attempt first."
            )
    unlocked = set(unlocked_exhibit_ids)
    for e in case.exhibits:
        if e.id in unlocked:
            parts.append(
                f"Exhibit {e.id} ({e.title}): {json.dumps(e.data)} — {e.so_what}"
            )
    return "\n".join(parts)


def tutor_slice(lesson: Lesson, *, section_index: int) -> str:
    """Tutor-visible content for one section. Quiz answer keys stay out of the
    section Q&A context; the flow supplies an explanation only after grading."""
    s = lesson.sections[section_index]
    parts = [f"Lesson: {lesson.meta.title}", f"Section: {s.heading}", s.content]
    if s.worked_example:
        parts.append(f"Worked example: {s.worked_example}")
    parts.append(f"When to use: {lesson.when_to_use}")
    parts.append(f"When not to use: {lesson.when_not_to_use}")
    return "\n".join(parts)


def _assemble(
    system_prompt: str,
    *,
    stage_facts: str = "",
    content_slice: str = "",
    transcript: Sequence[Message] = (),
    math_verdicts: str = "",
) -> list[Message]:
    """Order per §3: system prompt + stage facts + content slice, then the
    transcript window, then math-checker verdicts last (most recent instruction)."""
    context = system_prompt
    for label, body in (("Stage", stage_facts), ("Content", content_slice)):
        if body:
            context += f"\n\n[{label}]\n{body}"
    messages: list[Message] = [{"role": "system", "content": context}]
    messages += [{"role": t["role"], "content": t["content"]} for t in transcript]
    if math_verdicts:
        messages.append({"role": "system", "content": f"[Math check]\n{math_verdicts}"})
    return messages


def build_interviewer_context(
    case: Case,
    *,
    phase_name: str,
    unlocked_exhibit_ids: Sequence[str] = (),
    transcript: Sequence[Message] = (),
    stage_facts: str = "",
    math_verdicts: str = "",
    pushback_intensity: str = "gentle",
) -> list[Message]:
    system = render("interviewer", pushback_intensity=pushback_intensity)
    content = interviewer_slice(
        case, phase_name=phase_name, unlocked_exhibit_ids=unlocked_exhibit_ids
    )
    return _assemble(
        system,
        stage_facts=stage_facts,
        content_slice=content,
        transcript=transcript,
        math_verdicts=math_verdicts,
    )


def build_coach_context(
    case: Case,
    *,
    phase_name: str,
    unlocked_exhibit_ids: Sequence[str] = (),
    transcript: Sequence[Message] = (),
    stage_facts: str = "",
    math_verdicts: str = "",
    reveal_model_approach: bool = True,
) -> list[Message]:
    system = render("coach")
    content = coach_slice(
        case,
        phase_name=phase_name,
        unlocked_exhibit_ids=unlocked_exhibit_ids,
        reveal_model_approach=reveal_model_approach,
    )
    return _assemble(
        system,
        stage_facts=stage_facts,
        content_slice=content,
        transcript=transcript,
        math_verdicts=math_verdicts,
    )


def build_tutor_context(
    lesson: Lesson,
    *,
    section_index: int,
    transcript: Sequence[Message] = (),
    stage_facts: str = "",
) -> list[Message]:
    system = render("tutor")
    content = tutor_slice(lesson, section_index=section_index)
    return _assemble(
        system,
        stage_facts=stage_facts,
        content_slice=content,
        transcript=transcript,
    )
