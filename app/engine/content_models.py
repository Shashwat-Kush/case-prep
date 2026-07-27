"""Executable schemas for the four content types (03_CONTENT_SPEC §2).

These pydantic models are the canonical form of the content spec; the authoring
guide tracks them and they win on conflict (03_CONTENT_SPEC §7). Modes, personas,
and rubric dimensions are centralized here so no synonyms leak elsewhere (04 §3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, RootModel, model_validator

# --- Id / key patterns (04_ENGINEERING_RULES §3) -----------------------------

_KEBAB = r"[a-z0-9]+(-[a-z0-9]+)*"
CASE_ID = rf"^case-{_KEBAB}$"
GUESS_ID = rf"^guess-{_KEBAB}$"
LESSON_ID = rf"^lesson-{_KEBAB}$"
BENCHMARK_KEY = r"^[a-z0-9]+(_[a-z0-9]+)*$"


# --- Enums -------------------------------------------------------------------


class CaseMode(StrEnum):
    guided = "guided"
    standard = "standard"
    cold = "cold"


class GuessMode(StrEnum):
    coached = "coached"
    timed = "timed"


class Persona(StrEnum):
    interviewer = "interviewer"
    coach = "coach"
    tutor = "tutor"


class ApproachType(StrEnum):
    top_down = "top_down"
    bottom_up = "bottom_up"


# --- Shared pieces -----------------------------------------------------------


class DimensionRubric(BaseModel):
    """Scoring anchors keyed by score 1-5 (01_PRD Module C, 07_PROMPTS §4)."""

    anchors: dict[int, str]


class Clarification(BaseModel):
    question_pattern: str
    answer: str


# --- Cases (03_CONTENT_SPEC §2.1) --------------------------------------------


class CaseMeta(BaseModel):
    id: str = Field(pattern=CASE_ID)
    title: str
    type: str
    industry: str
    difficulty: str
    est_minutes: int
    prerequisite_concepts: list[str] = []
    diagnostic: bool = False


class Exhibit(BaseModel):
    id: str
    title: str
    data: Any
    unlock_condition: str
    so_what: str


class Coaching(BaseModel):
    explain: str
    model_approach_for_phase: str


class Phase(BaseModel):
    name: str
    interviewer_instructions: str
    coaching: Coaching | None = None
    time_budget: int | None = None
    pass_criteria: str | None = None


class CommonError(BaseModel):
    """A known-wrong approach. `note` is required; `value` (optional) is the
    numeric wrong result so the math checker can recognise it (T-023). Accepts a
    bare string (note only) or a {value, note} object (docs/decisions.md)."""

    note: str = ""
    value: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_string(cls, data):
        return {"note": data} if isinstance(data, str) else data


class MathCheckpoint(BaseModel):
    inputs: str  # arithmetic expression over literal numbers (docs/decisions.md)
    expected_value: float
    tolerance: float = 0.0
    common_errors: list[CommonError] = []


class Curveball(BaseModel):
    trigger_phase: str
    injected_fact: str


class ModelAnswer(BaseModel):
    framework: str
    key_insights: list[str]
    recommendation: str
    walkthrough: str


class CaseRubric(BaseModel):
    structure: DimensionRubric
    math: DimensionRubric
    judgment: DimensionRubric
    communication: DimensionRubric
    synthesis: DimensionRubric


class Case(BaseModel):
    meta: CaseMeta
    prompt: str
    clarifying: list[Clarification] = []
    facts: dict[str, Any] = {}
    exhibits: list[Exhibit] = []
    phases: list[Phase]
    math_checkpoints: list[MathCheckpoint] = []
    curveballs: list[Curveball] = []
    model_answer: ModelAnswer
    rubric: CaseRubric


# --- Guesstimates (03_CONTENT_SPEC §2.2) -------------------------------------


class GuessMeta(BaseModel):
    id: str = Field(pattern=GUESS_ID)
    title: str
    difficulty: str
    est_minutes: int
    region: str
    diagnostic: bool = False


class TreeSegment(BaseModel):
    segment: str
    benchmark_refs: list[str] = []
    derivation: str
    value: float
    tolerance: float = 0.0


class Approach(BaseModel):
    recommended: ApproachType
    tree: list[TreeSegment]


class AnswerRange(BaseModel):
    low: float
    high: float


class GuessRubric(BaseModel):
    approach: DimensionRubric
    segmentation: DimensionRubric
    arithmetic: DimensionRubric
    sanity_check: DimensionRubric


class Guesstimate(BaseModel):
    meta: GuessMeta
    prompt: str
    clarifications: list[Clarification] = []
    approach: Approach
    answer_range: AnswerRange
    common_traps: list[str] = []
    rubric: GuessRubric


# --- Lessons (03_CONTENT_SPEC §2.3) ------------------------------------------


class LessonMeta(BaseModel):
    id: str = Field(pattern=LESSON_ID)
    title: str
    concepts_taught: list[str]
    order_hint: int | None = None


class Section(BaseModel):
    heading: str
    content: str
    worked_example: str | None = None


class QuizItem(BaseModel):
    question: str
    options: list[str] | None = None
    answer: str
    explanation: str


class Lesson(BaseModel):
    meta: LessonMeta
    sections: list[Section]
    when_to_use: str
    when_not_to_use: str
    quiz: list[QuizItem] = []


# --- Benchmarks (03_CONTENT_SPEC §2.4) ---------------------------------------


class Benchmark(BaseModel):
    value: float
    unit: str
    as_of: int
    source_note: str = ""


class Benchmarks(RootModel[dict[str, Benchmark]]):
    """The single canonical facts file; keys are snake_case benchmark ids."""

    def __getitem__(self, key: str) -> Benchmark:
        return self.root[key]

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def keys(self):
        return self.root.keys()
