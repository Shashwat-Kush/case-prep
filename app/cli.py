"""Terminal chat REPL (T-019): run a lesson or a guided/standard case end to end,
typed and streaming, against the provider router.

The LLM and IO are seams so the flows can be driven by a fake in tests:
`chat(messages) -> Iterable[str]` yields reply tokens; `read()` returns a typed
line; `emit(text)` writes raw output. main() wires the real router + stdin/stdout.
End-of-case feedback is a single-call placeholder until the scoring orchestrator
(T-025).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from app.config import load_config
from app.engine.case_flow import CaseComplete, CaseFlow, CoachError
from app.engine.content_loader import ContentLoader
from app.engine.lesson_flow import LessonFlow
from app.llm.templates import Message
from app.providers.router import Router

Chat = Callable[[list[Message]], Iterable[str]]
Read = Callable[[], str]
Emit = Callable[[str], None]


def stream_reply(chat: Chat, messages: list[Message], emit: Emit) -> str:
    """Stream a reply token by token, echoing as it arrives; return the full text."""
    parts: list[str] = []
    for token in chat(messages):
        emit(token)
        parts.append(token)
    emit("\n")
    return "".join(parts)


def run_case(flow: CaseFlow, chat: Chat, read: Read, emit: Emit) -> None:
    case = flow.case
    persona = "coach" if flow.mode == "guided" else "interviewer"
    emit(f"Case: {case.meta.title}  [{flow.mode}]\n{case.prompt}\n")
    emit("\nCommands: /next  /exhibit <id>  /reveal (guided)  /quit\n")

    while True:
        emit(f"\n--- Phase: {flow.phase_name} ---\n")
        if flow.mode == "guided" and flow.has_coaching:
            emit(f"[Coach] {flow.coach_explain()}\n")
            emit("Attempt this phase, then /reveal, then /next.\n")

        if not _phase_loop(flow, persona, chat, read, emit):
            return  # user quit
        if flow.is_terminal:
            break
        flow.advance()

    _end_feedback(flow, chat, emit)


def _phase_loop(
    flow: CaseFlow, persona: str, chat: Chat, read: Read, emit: Emit
) -> bool:
    """Run one phase's turns. Returns False if the user quit, else True on /next."""
    while True:
        emit("\nyou> ")
        line = read().strip()
        if line == "/quit":
            emit("\nEnded.\n")
            return False
        if line == "/next":
            return True
        if line == "/reveal":
            try:
                emit(f"[Coach] {flow.coach_reveal()}\n")
            except CoachError as e:
                emit(f"({e})\n")
            continue
        if line.startswith("/exhibit"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                try:
                    flow.unlock_exhibit(parts[1])
                    emit(f"(unlocked {parts[1]})\n")
                except KeyError as e:
                    emit(f"({e})\n")
            continue
        flow.record_turn("user", line)
        reply = stream_reply(chat, flow.context(persona), emit)
        flow.record_turn("assistant", reply)


def _end_feedback(flow: CaseFlow, chat: Chat, emit: Emit) -> None:
    emit("\n=== End of case — quick feedback ===\n")
    messages: list[Message] = [
        {
            "role": "system",
            "content": (
                "You are a case-interview coach. In 3-4 sentences, give brief, "
                "encouraging feedback on the conversation so far. Do not invent facts."
            ),
        },
        *flow.transcript_window(),
    ]
    stream_reply(chat, messages, emit)


def run_lesson(flow: LessonFlow, chat: Chat, read: Read, emit: Emit) -> None:
    while flow.stage == "teaching":
        s = flow.current_section
        emit(f"\n## {s.heading}\n{s.content}\n")
        if s.worked_example:
            emit(f"Example: {s.worked_example}\n")
        emit("\n(Ask a question, or /next to continue.)\n")
        if not _teach_loop(flow, chat, read, emit):
            return

    while flow.stage == "quiz":
        q = flow.current_question
        emit(f"\nQuiz: {q.question}\n")
        for opt in q.options or []:
            emit(f"  - {opt}\n")
        emit("\nyou> ")
        ans = read().strip()
        if ans == "/quit":
            return
        correct = flow.answer(ans)
        emit("Correct!\n" if correct else f"Not quite — answer: {q.answer}\n")
        emit(f"{q.explanation}\n")

    cov = flow.coverage()
    emit(
        f"\nDone. Quiz {cov.quiz_correct}/{cov.quiz_total}. "
        f"Concepts covered: {', '.join(cov.concepts_taught)}\n"
    )


def _teach_loop(flow: LessonFlow, chat: Chat, read: Read, emit: Emit) -> bool:
    """Q&A within a section. Returns False if the user quit, else True on /next."""
    while True:
        emit("\nyou> ")
        line = read().strip()
        if line == "/quit":
            return False
        if line == "/next":
            flow.advance_section()
            return True
        flow.record_turn("user", line)
        reply = stream_reply(chat, flow.context(), emit)
        flow.record_turn("assistant", reply)


def _llm_grader(chat: Chat):
    """Free-form quiz grader for lessons without options (seed lessons are all
    MCQ, so this is only used by future free-form questions)."""

    def grade(item, user_answer: str) -> bool:
        messages: list[Message] = [
            {
                "role": "system",
                "content": "Reply with exactly 'yes' or 'no': is the candidate's "
                "answer essentially correct given the reference answer?",
            },
            {
                "role": "user",
                "content": (
                    f"Question: {item.question}\n"
                    f"Reference: {item.answer}\n"
                    f"Candidate: {user_answer}"
                ),
            },
        ]
        return "".join(chat(messages)).strip().lower().startswith("y")

    return grade


def _list_content(library) -> None:
    print("Usage: python -m app.cli <content-id> [--mode guided|standard]\n")
    print("Cases:")
    for cid in sorted(library.cases):
        print(f"  {cid}")
    print("Lessons:")
    for lid in sorted(library.lessons):
        print(f"  {lid}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    config = load_config()
    library = ContentLoader(Path(".")).library

    if not argv:
        _list_content(library)
        return 0

    content_id = argv[0]
    mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "standard"
    window = config.context.transcript_window_turns

    router = Router(config)
    chat: Chat = router.chat
    read: Read = input

    def emit(text: str) -> None:
        print(text, end="", flush=True)

    if content_id in library.cases:
        try:
            flow = CaseFlow(
                library.cases[content_id],
                mode=mode,
                transcript_window_turns=window,
            )
        except ValueError as e:
            print(e)
            return 1
        try:
            run_case(flow, chat, read, emit)
        except CaseComplete:
            pass
    elif content_id in library.lessons:
        lesson_flow = LessonFlow(
            library.lessons[content_id],
            transcript_window_turns=window,
            free_form_grader=_llm_grader(chat),
        )
        run_lesson(lesson_flow, chat, read, emit)
    elif content_id in library.guesstimates:
        print("Guesstimates arrive in Phase 2.")
        return 1
    else:
        print(f"Unknown content id: {content_id}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
