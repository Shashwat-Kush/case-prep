"""FastAPI app + streaming transport (T-040/T-041, 02_ARCHITECTURE §3).

Transport is Server-Sent Events over plain HTTP (G-2: HTML/JS + SSE — one-way
token streaming is all a single-user loop needs; the browser POSTs a turn and the
server streams the reply back). The backend owns all state (ADR-2): case, lesson,
and guesstimate flows live server-side in the engine, keyed by an opaque session
id; the browser holds only that id plus whatever `state()` returns.

Every content type presents the same session contract — `state()` (the current
view), `reply_tokens()` (streamed chat), `act(action, value)` (discrete controls:
advance, quiz answer, estimate, coach reveal, exhibit unlock) — so the routes and
the frontend are uniform. `create_app(engine)` takes the engine as a seam so route
contracts test against a fake; `main()` binds the live engine to localhost only.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import Config, load_config
from app.engine.case_flow import CaseFlow, CoachError
from app.engine.content_loader import ContentLoader
from app.engine.guess_flow import GuessComplete, GuessFlow, GuessFlowError
from app.engine.lesson_flow import LessonFlow
from app.engine.scoring import (
    ScoringError,
    assemble_feedback,
    persist_scorecard,
    reveal_model_answer,
    score_case,
)
from app.engine.session_manager import SessionManager
from app.providers.router import Router

WEB_DIR = Path(__file__).parent.parent / "web"


class WebSession(Protocol):
    def state(self) -> dict: ...
    def reply_tokens(self, text: str) -> Iterator[str]: ...
    def act(self, action: str, value: str | None) -> dict: ...


class Engine(Protocol):
    def content_list(self) -> dict: ...
    def start(self, content_id: str, mode: str) -> str: ...
    def get(self, session_id: str) -> WebSession: ...


class CreateReq(BaseModel):
    content_id: str
    mode: str = "standard"


class MessageReq(BaseModel):
    text: str


class ActionReq(BaseModel):
    action: str
    value: str | None = None


def _sse(tokens: Iterator[str]) -> Iterator[str]:
    for tok in tokens:
        yield f"data: {json.dumps({'token': tok})}\n\n"
    yield "data: [DONE]\n\n"


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="CasePrep Local")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/content")
    def content() -> dict:
        return engine.content_list()

    @app.post("/api/session")
    def create_session(req: CreateReq) -> dict:
        try:
            sid = engine.start(req.content_id, req.mode)
        except KeyError as e:
            raise HTTPException(404, f"unknown content id: {req.content_id}") from e
        except ValueError as e:  # e.g. guided mode on a case with no coaching
            raise HTTPException(400, str(e)) from e
        return {"session_id": sid, **engine.get(sid).state()}

    @app.post("/api/session/{sid}/message")
    def message(sid: str, req: MessageReq) -> StreamingResponse:
        session = _lookup(engine, sid)
        return StreamingResponse(
            _sse(session.reply_tokens(req.text)), media_type="text/event-stream"
        )

    @app.post("/api/session/{sid}/action")
    def action(sid: str, req: ActionReq) -> dict:
        return _lookup(engine, sid).act(req.action, req.value)

    @app.get("/api/session/{sid}/exhibit/{exhibit_id}")
    def exhibit(sid: str, exhibit_id: str) -> dict:
        # Server-side gate (defense in depth): a locked exhibit's data never
        # leaves the backend, whatever the client requests (07_PROMPTS §4).
        getter = getattr(_lookup(engine, sid), "exhibit", None)
        if getter is None:
            raise HTTPException(404, "this session has no exhibits")
        try:
            return getter(exhibit_id)
        except KeyError as e:
            raise HTTPException(404, f"unknown exhibit: {exhibit_id}") from e
        except PermissionError as e:
            raise HTTPException(403, f"exhibit is locked: {exhibit_id}") from e

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def _lookup(engine: Engine, sid: str) -> WebSession:
    try:
        return engine.get(sid)
    except KeyError as e:
        raise HTTPException(404, f"unknown session: {sid}") from e


def _stream(session: SessionManager, flow, phase: str, chat, messages) -> Iterator[str]:
    """Stream a chat reply, echoing tokens and recording both turns (ADR-2)."""
    stream = chat(messages)
    parts: list[str] = []
    for tok in stream:
        parts.append(tok)
        yield tok
    reply = "".join(parts)
    flow.record_turn("assistant", reply)
    rec = getattr(stream, "record", None)
    session.record_turn(
        "assistant",
        reply,
        phase=phase,
        provider=getattr(rec, "provider", None),
        latency_ms=getattr(rec, "latency_ms", None),
    )


# --- Case ---------------------------------------------------------------------


class LiveCaseSession:
    def __init__(self, flow: CaseFlow, chat, session: SessionManager, config: Config):
        self._flow = flow
        self._chat = chat
        self._session = session
        self._config = config
        self._persona = "coach" if flow.mode == "guided" else "interviewer"
        self._exhibits = {e.id: e for e in flow.case.exhibits}
        self._end_payload: dict | None = None

    def state(self) -> dict:
        if self._end_payload is not None:
            return {"type": "case", "done": True, **self._end_payload}
        s = {
            "type": "case",
            "done": False,
            "title": self._flow.case.meta.title,
            "prompt": self._flow.case.prompt,
            "mode": self._flow.mode,
            "phase": self._flow.phase_name,
            "persona": self._persona,
            "last": self._flow.is_terminal,
            "exhibits": sorted(self._flow.unlocked_exhibit_ids),
            "time_budget_s": self._flow.phase_budget_s,
        }
        if self._flow.mode == "guided" and self._flow.has_coaching:
            s["coaching"] = self._flow.coach_explain()
            s["attempted"] = self._flow.attempted
        return s

    def reply_tokens(self, text: str) -> Iterator[str]:
        phase = self._flow.phase_name
        self._flow.record_turn("user", text)
        self._session.record_turn("user", text, phase=phase)
        messages = self._flow.context(self._persona)
        yield from _stream(self._session, self._flow, phase, self._chat, messages)

    def act(self, action: str, value: str | None) -> dict:
        if action == "advance":
            if self._flow.is_terminal:
                self._end()
            else:
                self._flow.advance()
            return self.state()
        if action == "reveal":
            try:
                return {**self.state(), "coach_reveal": self._flow.coach_reveal()}
            except CoachError as e:
                return {**self.state(), "error": str(e)}
        if action == "exhibit":
            try:
                self._flow.unlock_exhibit(value or "")
            except KeyError as e:
                return {**self.state(), "error": str(e)}
            return self.state()
        raise HTTPException(400, f"unknown action: {action}")

    def exhibit(self, exhibit_id: str) -> dict:
        """An unlocked exhibit's renderable payload. `so_what` (the takeaway) is
        withheld — the candidate interprets the data themselves (07_PROMPTS §4)."""
        ex = self._exhibits.get(exhibit_id)
        if ex is None:
            raise KeyError(exhibit_id)
        if not self._flow.is_unlocked(exhibit_id):
            raise PermissionError(exhibit_id)
        return {"id": ex.id, "title": ex.title, "data": ex.data}

    def _end(self) -> None:
        if self._end_payload is not None:
            return
        self._flow.close()  # capture the final phase's timing
        overruns = [t["phase"] for t in self._flow.overruns]
        if overruns:
            self._session.record_turn(
                "system", "overran phases: " + ", ".join(overruns), phase="pacing"
            )
        payload: dict = {
            "model_answer": reveal_model_answer(self._flow.case),
            "overruns": overruns,
        }
        try:
            card = score_case(
                self._flow.case, self._flow.transcript, self._chat, config=self._config
            )
        except ScoringError:
            card = None
        if card is not None:
            persist_scorecard(self._session.store, self._session.session_id, card)
            if self._config.score_visibility:
                payload["feedback"] = assemble_feedback(self._flow.case, card)
        self._end_payload = payload


# --- Lesson -------------------------------------------------------------------


class LiveLessonSession:
    def __init__(self, flow: LessonFlow, chat, session: SessionManager):
        self._flow = flow
        self._chat = chat
        self._session = session

    def state(self) -> dict:
        stage = self._flow.stage
        if stage == "teaching":
            s = self._flow.current_section
            return {
                "type": "lesson",
                "stage": "teaching",
                "done": False,
                "heading": s.heading,
                "content": s.content,
                "worked_example": s.worked_example,
            }
        if stage == "quiz":
            q = self._flow.current_question
            return {
                "type": "lesson",
                "stage": "quiz",
                "done": False,
                "question": q.question,
                "options": q.options or [],
            }
        cov = self._flow.coverage()
        return {
            "type": "lesson",
            "stage": "complete",
            "done": True,
            "coverage": {
                "quiz_correct": cov.quiz_correct,
                "quiz_total": cov.quiz_total,
                "concepts": cov.concepts_taught,
            },
        }

    def reply_tokens(self, text: str) -> Iterator[str]:
        phase = self._flow.stage
        self._flow.record_turn("user", text)
        self._session.record_turn("user", text, phase=phase)
        yield from _stream(
            self._session, self._flow, phase, self._chat, self._flow.context()
        )

    def act(self, action: str, value: str | None) -> dict:
        if action == "advance":
            if self._flow.stage == "teaching":
                self._flow.advance_section()
            return self.state()
        if action == "answer":
            if self._flow.stage != "quiz":
                return {**self.state(), "error": "not in the quiz"}
            item = self._flow.current_question
            correct = self._flow.answer(value or "")
            return {
                **self.state(),
                "correct": correct,
                "answer": item.answer,
                "explanation": item.explanation,
            }
        raise HTTPException(400, f"unknown action: {action}")


# --- Guesstimate --------------------------------------------------------------


class LiveGuessSession:
    def __init__(self, flow: GuessFlow, chat, session: SessionManager):
        self._flow = flow
        self._chat = chat
        self._session = session

    def state(self) -> dict:
        step = self._flow.step
        s = {
            "type": "guess",
            "step": step,
            "done": self._flow.is_complete,
            "title": self._flow.guess.meta.title,
            "prompt": self._flow.guess.prompt,
            "mode": self._flow.mode,
        }
        if step == "estimation":
            s["segment"] = self._flow.current_segment.segment
        if self._flow.is_complete:
            s["estimates"] = [
                {"segment": e.segment, "value": e.value} for e in self._flow.estimates
            ]
        return s

    def reply_tokens(self, text: str) -> Iterator[str]:
        step = self._flow.step
        self._flow.record_turn("user", text)
        self._session.record_turn("user", text, phase=step)
        yield from _stream(
            self._session, self._flow, step, self._chat, self._flow.context()
        )

    def act(self, action: str, value: str | None) -> dict:
        if action == "advance":
            try:
                self._flow.advance()
            except (GuessFlowError, GuessComplete) as e:
                return {**self.state(), "error": str(e)}
            return self.state()
        if action == "estimate":
            try:
                est = self._flow.submit_estimate(float(value or "nan"))
            except (GuessFlowError, TypeError, ValueError) as e:
                return {**self.state(), "error": str(e)}
            return {
                **self.state(),
                "submitted": {"segment": est.segment, "value": est.value},
            }
        raise HTTPException(400, f"unknown action: {action}")


# --- Live engine --------------------------------------------------------------


class LiveEngine:
    def __init__(self, config: Config, library, store, chat):
        self._config = config
        self._library = library
        self._store = store
        self._chat = chat
        self._window = config.context.transcript_window_turns
        self._sessions: dict[str, WebSession] = {}

    def content_list(self) -> dict:
        return {
            "cases": [
                {
                    "id": c.meta.id,
                    "title": c.meta.title,
                    "modes": ["standard", "guided"],
                }
                for c in sorted(self._library.cases.values(), key=lambda x: x.meta.id)
            ],
            "lessons": [
                {"id": lsn.meta.id, "title": lsn.meta.title}
                for lsn in sorted(
                    self._library.lessons.values(), key=lambda x: x.meta.id
                )
            ],
            "guesstimates": [
                {"id": g.meta.id, "title": g.meta.title, "modes": ["coached", "timed"]}
                for g in sorted(
                    self._library.guesstimates.values(), key=lambda x: x.meta.id
                )
            ],
        }

    def start(self, content_id: str, mode: str) -> str:
        lib = self._library
        if content_id in lib.cases:
            flow = CaseFlow(
                lib.cases[content_id], mode=mode, transcript_window_turns=self._window
            )
            session = self._new_session(content_id, "case", mode)
            sess: WebSession = LiveCaseSession(flow, self._chat, session, self._config)
        elif content_id in lib.lessons:
            flow = LessonFlow(
                lib.lessons[content_id], transcript_window_turns=self._window
            )
            session = self._new_session(content_id, "lesson", None)
            sess = LiveLessonSession(flow, self._chat, session)
        elif content_id in lib.guesstimates:
            flow = GuessFlow(
                lib.guesstimates[content_id],
                mode=mode,
                transcript_window_turns=self._window,
            )
            session = self._new_session(content_id, "guesstimate", mode)
            sess = LiveGuessSession(flow, self._chat, session)
        else:
            raise KeyError(content_id)
        sid = uuid4().hex
        self._sessions[sid] = sess
        return sid

    def _new_session(
        self, content_id: str, content_type: str, mode: str | None
    ) -> SessionManager:
        return SessionManager(
            self._store, content_id=content_id, content_type=content_type, mode=mode
        )

    def get(self, session_id: str) -> WebSession:
        return self._sessions[session_id]


def main() -> None:
    import uvicorn

    from app.db.store import Store

    config = load_config()
    library = ContentLoader(Path(".")).library
    store = Store("app.db")
    chat = Router(config).chat
    app = create_app(LiveEngine(config, library, store, chat))
    uvicorn.run(app, host=config.host, port=config.port)  # localhost-only (04 §8)


if __name__ == "__main__":
    main()
