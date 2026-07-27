"""Terminal chat REPL (T-019, persistence wired in T-021): run a lesson or a
guided/standard case end to end, typed and streaming, against the provider
router, recording every turn to the store as it happens.

The LLM and IO are seams so the flows can be driven by a fake in tests:
`chat(messages) -> stream` yields reply tokens and optionally carries a `.record`
(provider, latency); `read()` returns a typed line; `emit(text)` writes raw
output. Passing `session=None` runs a flow without persistence (pure-flow tests).
main() wires the real router, store, and stdin/stdout. End-of-case runs chunked
scoring (T-025), then reveals the model answer and anchored feedback (T-026).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from app.config import Config, load_config
from app.db.store import Store
from app.engine.case_flow import CaseComplete, CaseFlow, CoachError
from app.engine.content_loader import ContentLoader
from app.engine.drills import KINDS, run_sprint
from app.engine.lesson_flow import LessonFlow
from app.engine.scoring import (
    ScoringError,
    assemble_feedback,
    persist_scorecard,
    reveal_model_answer,
    score_case,
)
from app.engine.session_manager import SessionManager
from app.llm.templates import Message
from app.providers.router import Router

Chat = Callable[[list[Message]], Iterable[str]]
Read = Callable[[], str]
Emit = Callable[[str], None]


def stream_reply(chat: Chat, messages: list[Message], emit: Emit):
    """Stream a reply token by token, echoing as it arrives. Returns the full
    text and the stream's telemetry record (or None for a fake without one)."""
    stream = chat(messages)
    parts: list[str] = []
    for token in stream:
        emit(token)
        parts.append(token)
    emit("\n")
    return "".join(parts), getattr(stream, "record", None)


def _persist(session, role, text, phase, record=None) -> None:
    if session is not None:
        session.record_turn(
            role,
            text,
            phase=phase,
            provider=getattr(record, "provider", None),
            latency_ms=getattr(record, "latency_ms", None),
        )


def run_case(
    flow: CaseFlow,
    chat: Chat,
    read: Read,
    emit: Emit,
    session: SessionManager | None = None,
    config: Config | None = None,
) -> None:
    case = flow.case
    persona = "coach" if flow.mode == "guided" else "interviewer"
    emit(f"Case: {case.meta.title}  [{flow.mode}]\n{case.prompt}\n")
    emit("\nCommands: /next  /exhibit <id>  /reveal (guided)  /quit\n")

    while True:
        emit(f"\n--- Phase: {flow.phase_name} ---\n")
        if flow.mode == "guided" and flow.has_coaching:
            emit(f"[Coach] {flow.coach_explain()}\n")
            emit("Attempt this phase, then /reveal, then /next.\n")

        if not _phase_loop(flow, persona, chat, read, emit, session):
            return  # user quit
        if flow.is_terminal:
            break
        flow.advance()

    _end_feedback(flow, chat, emit, session, config)


def _phase_loop(flow, persona, chat, read, emit, session) -> bool:
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
        _persist(session, "user", line, flow.phase_name)
        reply, record = stream_reply(chat, flow.context(persona), emit)
        flow.record_turn("assistant", reply)
        _persist(session, "assistant", reply, flow.phase_name, record)


def _end_feedback(flow, chat, emit, session, config) -> None:
    """Score the case (chunked, T-025), show anchored feedback and the model
    answer. Scoring is skipped when no config is wired (pure-flow tests) or the
    provider can't return the scoring JSON — the reveal is always shown."""
    emit("\n=== End of case ===\n")
    if config is not None:
        try:
            card = score_case(flow.case, flow.transcript, chat, config=config)
        except ScoringError:
            card = None
        if card is not None:
            emit("\n" + assemble_feedback(flow.case, card) + "\n")
            if session is not None:
                persist_scorecard(session.store, session.session_id, card)
    emit("\n--- Model answer ---\n")
    emit(reveal_model_answer(flow.case) + "\n")


def run_lesson(
    flow: LessonFlow,
    chat: Chat,
    read: Read,
    emit: Emit,
    session: SessionManager | None = None,
) -> None:
    while flow.stage == "teaching":
        s = flow.current_section
        emit(f"\n## {s.heading}\n{s.content}\n")
        if s.worked_example:
            emit(f"Example: {s.worked_example}\n")
        emit("\n(Ask a question, or /next to continue.)\n")
        if not _teach_loop(flow, chat, read, emit, session):
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
        _persist(session, "user", ans, "quiz")
        correct = flow.answer(ans)
        emit("Correct!\n" if correct else f"Not quite — answer: {q.answer}\n")
        emit(f"{q.explanation}\n")

    cov = flow.coverage()
    emit(
        f"\nDone. Quiz {cov.quiz_correct}/{cov.quiz_total}. "
        f"Concepts covered: {', '.join(cov.concepts_taught)}\n"
    )


def _teach_loop(flow, chat, read, emit, session) -> bool:
    """Q&A within a section. Returns False if the user quit, else True on /next."""
    while True:
        emit("\nyou> ")
        line = read().strip()
        if line == "/quit":
            return False
        if line == "/next":
            flow.advance_section()
            return True
        phase = flow.current_section.heading
        flow.record_turn("user", line)
        _persist(session, "user", line, phase)
        reply, record = stream_reply(chat, flow.context(), emit)
        flow.record_turn("assistant", reply)
        _persist(session, "assistant", reply, phase, record)


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
        text, _ = stream_reply(chat, messages, lambda _: None)
        return text.strip().lower().startswith("y")

    return grade


def _list_content(library) -> None:
    print(
        "Usage: python -m app.cli <content-id> [--mode guided|standard] [--offline]\n"
    )
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

    if argv[0] == "drills":  # LLM-free mental-math sprint (T-063), offline
        n = int(argv[argv.index("-n") + 1]) if "-n" in argv else 5
        kinds = (argv[argv.index("--kind") + 1],) if "--kind" in argv else KINDS
        store = Store("app.db")
        try:
            emit = lambda t: print(t, end="", flush=True)  # noqa: E731
            run_sprint(store, input, emit, n=n, kinds=kinds)
        finally:
            store.close()
        return 0

    content_id = argv[0]
    mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "standard"
    if "--offline" in argv:  # the offline profile: route to local Ollama only
        config = config.model_copy(update={"offline": True})
    window = config.context.transcript_window_turns

    chat: Chat = Router(config).chat
    read: Read = input

    def emit(text: str) -> None:
        print(text, end="", flush=True)

    if content_id in library.cases:
        try:
            flow = CaseFlow(
                library.cases[content_id], mode=mode, transcript_window_turns=window
            )
        except ValueError as e:
            print(e)
            return 1
        store = Store("app.db")
        session = SessionManager(
            store, content_id=content_id, content_type="case", mode=mode
        )
        try:
            run_case(flow, chat, read, emit, session, config)
        except CaseComplete:
            pass
        finally:
            session.end()
            store.close()
    elif content_id in library.lessons:
        store = Store("app.db")
        session = SessionManager(store, content_id=content_id, content_type="lesson")
        lesson_flow = LessonFlow(
            library.lessons[content_id],
            transcript_window_turns=window,
            free_form_grader=_llm_grader(chat),
        )
        try:
            run_lesson(lesson_flow, chat, read, emit, session)
        finally:
            session.end()
            store.close()
    elif content_id in library.guesstimates:
        print("Guesstimates arrive in Phase 2.")
        return 1
    else:
        print(f"Unknown content id: {content_id}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
