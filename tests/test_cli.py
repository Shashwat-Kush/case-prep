import json
from pathlib import Path

from app.cli import main, run_case, run_lesson
from app.engine.case_flow import CaseFlow
from app.engine.content_models import Case, Lesson
from app.engine.lesson_flow import LessonFlow

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"
EXPLAIN = "A strong candidate isolates whether the problem is revenue or cost."
REVEAL = "Decompose profit into revenue and cost, then drill into cost lines."


def _case() -> Case:
    return Case.model_validate(
        json.loads((FIXT / "cases" / "case-cement-profitability.json").read_text())
    )


def _lesson() -> Lesson:
    return Lesson.model_validate(
        json.loads((FIXT / "lessons" / "lesson-profitability.json").read_text())
    )


def _fake_chat(reply: str = "Understood."):
    def chat(messages):
        for word in reply.split():
            yield word + " "

    return chat


def _reader(lines):
    it = iter(lines)
    return lambda: next(it)


class Sink:
    def __init__(self):
        self.buf: list[str] = []

    def __call__(self, s: str) -> None:
        self.buf.append(s)

    @property
    def text(self) -> str:
        return "".join(self.buf)


def test_guided_case_full_run_reaches_terminal_in_order():
    flow = CaseFlow(_case(), mode="guided")  # opening, structuring, analysis, synthesis
    lines = ["/next", "/next", "my attempt", "/reveal", "/next", "/next"]
    out = Sink()
    run_case(flow, _fake_chat("Good point."), _reader(lines), out)

    assert flow.is_terminal
    t = out.text
    assert EXPLAIN in t and REVEAL in t
    assert t.index(EXPLAIN) < t.index(REVEAL)  # explain before reveal
    assert "quick feedback" in t.lower()  # end-of-case feedback shown


def test_reveal_blocked_before_attempt_in_repl():
    flow = CaseFlow(_case(), mode="guided")
    lines = ["/next", "/next", "/reveal", "/quit"]  # reveal at analysis before attempt
    out = Sink()
    run_case(flow, _fake_chat(), _reader(lines), out)
    assert REVEAL not in out.text
    assert "before the candidate has attempted" in out.text


def test_standard_case_streams_and_unlocks_exhibit():
    flow = CaseFlow(_case())  # standard -> interviewer
    lines = [
        "what is going on?",
        "/next",
        "/next",
        "/exhibit ex-cost-breakdown",
        "/next",
        "/next",
    ]
    out = Sink()
    run_case(flow, _fake_chat("Tell me more."), _reader(lines), out)
    assert flow.is_terminal
    assert flow.is_unlocked("ex-cost-breakdown")
    assert "Tell me more." in out.text.replace("  ", " ").strip() or "more." in out.text


def test_lesson_full_run_grades_and_reports_coverage():
    flow = LessonFlow(_lesson())  # 1 section, 1 MCQ
    out = Sink()
    run_lesson(flow, _fake_chat(), _reader(["/next", "Revenue - Cost"]), out)
    assert flow.is_complete
    assert "Correct!" in out.text
    assert "Concepts covered: profit-tree" in out.text


def test_lesson_section_qa_streams():
    flow = LessonFlow(_lesson())
    out = Sink()
    run_lesson(
        flow,
        _fake_chat("Profit is revenue minus cost."),
        _reader(["what is profit?", "/next", "Revenue - Cost"]),
        out,
    )
    assert "minus cost." in out.text


def test_main_lists_content(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Cases:" in out and "Lessons:" in out
