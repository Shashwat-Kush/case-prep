import json
from pathlib import Path

import pytest

from app.engine.content_models import Lesson
from app.engine.lesson_flow import LessonFlow

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "content"
    / "valid"
    / "lessons"
    / "lesson-profitability.json"
)


def _lesson() -> Lesson:
    return Lesson.model_validate(json.loads(FIXTURE.read_text()))


def _free_form_lesson() -> Lesson:
    return Lesson.model_validate(
        {
            "meta": {"id": "lesson-ff", "title": "FF", "concepts_taught": ["c1"]},
            "sections": [{"heading": "S", "content": "body"}],
            "when_to_use": "x",
            "when_not_to_use": "y",
            "quiz": [
                {
                    "question": "Explain the profit tree.",
                    "answer": "Revenue minus cost, decomposed.",
                    "explanation": "e",
                }
            ],
        }
    )


def _blob(messages) -> str:
    return "\n".join(m["content"] for m in messages)


def test_flow_order_sections_then_quiz_then_complete():
    flow = _lesson()  # 1 section, 1 MCQ
    flow = LessonFlow(flow)
    assert flow.stage == "teaching"
    assert flow.current_section.heading == "Profit = Revenue - Cost"
    assert flow.advance_section() is None  # last section -> quiz
    assert flow.stage == "quiz"
    flow.answer("Revenue - Cost")
    assert flow.is_complete


def test_cannot_answer_while_teaching():
    flow = LessonFlow(_lesson())
    with pytest.raises(RuntimeError):
        flow.answer("Revenue - Cost")


def test_mcq_graded_deterministically():
    ok = LessonFlow(_lesson())
    ok.advance_section()
    assert ok.answer("revenue - cost") is True  # case/space-insensitive

    bad = LessonFlow(_lesson())
    bad.advance_section()
    assert bad.answer("Revenue + Cost") is False


def test_free_form_uses_injected_grader():
    calls = []

    def grader(item, user_answer):
        calls.append((item.question, user_answer))
        return True

    flow = LessonFlow(_free_form_lesson(), free_form_grader=grader)
    flow.advance_section()
    assert flow.answer("my attempt") is True
    assert calls == [("Explain the profit tree.", "my attempt")]


def test_free_form_without_grader_raises():
    flow = LessonFlow(_free_form_lesson())
    flow.advance_section()
    with pytest.raises(RuntimeError):
        flow.answer("my attempt")


def test_completion_emits_concepts_and_score():
    flow = LessonFlow(_lesson())
    flow.advance_section()
    flow.answer("Revenue - Cost")
    cov = flow.coverage()
    assert cov.lesson_id == "lesson-profitability"
    assert cov.concepts_taught == ["profit-tree", "revenue-cost-decomposition"]
    assert (cov.quiz_total, cov.quiz_correct) == (1, 1)


def test_context_grounded_in_current_section():
    flow = LessonFlow(_lesson())
    blob = _blob(flow.context())
    assert "Profit = Revenue - Cost" in blob  # section heading
    assert "Start every profitability case" in blob  # section content
    assert "Revenue + Cost" not in blob  # a quiz distractor is not leaked


def test_no_sections_rejected():
    lesson = _lesson()
    lesson.sections = []
    with pytest.raises(ValueError):
        LessonFlow(lesson)
