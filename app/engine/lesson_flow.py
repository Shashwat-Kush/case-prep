"""Lesson state machine (02_ARCHITECTURE §5): walk sections with free-form Q&A,
administer the quiz, emit a coverage result.

Quiz grading follows the math-checker principle (ADR-3): where a question has
options it is graded deterministically in Python; only genuinely free-form
answers go to an injected grader (a rubric LLM call in production, a fake in
tests). Transitions happen only through explicit engine calls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.engine.content_models import Lesson, QuizItem
from app.llm.templates import Message, build_tutor_context

FreeFormGrader = Callable[[QuizItem, str], bool]


@dataclass(frozen=True)
class CoverageResult:
    lesson_id: str
    concepts_taught: list[str]
    quiz_total: int
    quiz_correct: int


def _norm(text: str) -> str:
    return text.strip().casefold()


class LessonFlow:
    """Stages: teaching -> quiz -> complete. A lesson with no quiz goes straight
    from the last section to complete."""

    def __init__(
        self,
        lesson: Lesson,
        *,
        transcript_window_turns: int = 12,
        free_form_grader: FreeFormGrader | None = None,
    ):
        if not lesson.sections:
            raise ValueError(f"lesson {lesson.meta.id!r} has no sections")
        self._lesson = lesson
        self._window = transcript_window_turns
        self._grader = free_form_grader
        self._section_i = 0
        self._quiz_i = 0
        self._quiz_correct = 0
        self._stage = "teaching"
        self._transcript: list[Message] = []

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def is_complete(self) -> bool:
        return self._stage == "complete"

    # --- section walk-through ------------------------------------------------

    @property
    def current_section(self):
        return self._lesson.sections[self._section_i]

    def advance_section(self):
        """Move to the next section; after the last one, enter the quiz (or
        complete, if there is no quiz). Returns the new section, or None once
        teaching is over."""
        self._require("teaching")
        if self._section_i < len(self._lesson.sections) - 1:
            self._section_i += 1
            return self.current_section
        self._stage = "quiz" if self._lesson.quiz else "complete"
        return None

    # --- quiz ----------------------------------------------------------------

    @property
    def current_question(self) -> QuizItem:
        self._require("quiz")
        return self._lesson.quiz[self._quiz_i]

    def answer(self, user_answer: str) -> bool:
        """Grade the current question and advance. Options -> deterministic;
        free-form -> injected grader. Completing the last question ends the flow."""
        self._require("quiz")
        item = self._lesson.quiz[self._quiz_i]
        correct = self._grade(item, user_answer)
        if correct:
            self._quiz_correct += 1
        self._quiz_i += 1
        if self._quiz_i >= len(self._lesson.quiz):
            self._stage = "complete"
        return correct

    def _grade(self, item: QuizItem, user_answer: str) -> bool:
        if item.options:
            return _norm(user_answer) == _norm(item.answer)
        if self._grader is None:
            raise RuntimeError(f"free-form quiz item needs a grader: {item.question!r}")
        return bool(self._grader(item, user_answer))

    # --- transcript / context ------------------------------------------------

    def record_turn(self, role: str, content: str) -> None:
        self._transcript.append({"role": role, "content": content})

    def transcript_window(self) -> list[Message]:
        return self._transcript[-self._window :] if self._window > 0 else []

    def context(self, *, stage_facts: str = "") -> list[Message]:
        return build_tutor_context(
            self._lesson,
            section_index=self._section_i,
            transcript=self.transcript_window(),
            stage_facts=stage_facts,
        )

    # --- completion ----------------------------------------------------------

    def coverage(self) -> CoverageResult:
        return CoverageResult(
            lesson_id=self._lesson.meta.id,
            concepts_taught=list(self._lesson.meta.concepts_taught),
            quiz_total=len(self._lesson.quiz),
            quiz_correct=self._quiz_correct,
        )

    def _require(self, stage: str) -> None:
        if self._stage != stage:
            raise RuntimeError(f"expected stage {stage!r}, in {self._stage!r}")
