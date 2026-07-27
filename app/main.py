"""FastAPI app + streaming transport (T-040, 02_ARCHITECTURE §3).

Transport is Server-Sent Events over plain HTTP (G-2: HTML/JS + SSE — one-way
token streaming is all a single-user case loop needs; the browser POSTs a turn
and the server streams the reply back). The backend owns all state (ADR-2): case
flows live server-side in the engine, keyed by an opaque session id; the browser
holds only that id.

`create_app(engine)` takes the engine as a seam so route contracts can be tested
against a fake. `LiveEngine` is the real one (loader + router + store); `main()`
binds it to localhost only (config.host defaults to 127.0.0.1).
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
from app.engine.case_flow import CaseFlow
from app.engine.content_loader import ContentLoader
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
    """One in-flight case, server-side (the engine's unit of state)."""

    def opening(self) -> dict: ...
    def reply_tokens(self, text: str) -> Iterator[str]: ...
    def advance(self) -> dict: ...


class Engine(Protocol):
    def start(self, content_id: str, mode: str) -> str: ...
    def get(self, session_id: str) -> WebSession: ...


class CreateReq(BaseModel):
    content_id: str
    mode: str = "standard"


class MessageReq(BaseModel):
    text: str


def _sse(tokens: Iterator[str]) -> Iterator[str]:
    for tok in tokens:
        yield f"data: {json.dumps({'token': tok})}\n\n"
    yield "data: [DONE]\n\n"


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="CasePrep Local")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.post("/api/session")
    def create_session(req: CreateReq) -> dict:
        try:
            sid = engine.start(req.content_id, req.mode)
        except KeyError as e:
            raise HTTPException(404, f"unknown content id: {e}") from e
        return {"session_id": sid, **engine.get(sid).opening()}

    @app.post("/api/session/{sid}/message")
    def message(sid: str, req: MessageReq) -> StreamingResponse:
        session = _lookup(engine, sid)
        return StreamingResponse(
            _sse(session.reply_tokens(req.text)), media_type="text/event-stream"
        )

    @app.post("/api/session/{sid}/advance")
    def advance(sid: str) -> dict:
        return _lookup(engine, sid).advance()

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def _lookup(engine: Engine, sid: str) -> WebSession:
    try:
        return engine.get(sid)
    except KeyError as e:
        raise HTTPException(404, f"unknown session: {sid}") from e


# --- Live engine -------------------------------------------------------------


class LiveCaseSession:
    def __init__(self, flow: CaseFlow, chat, session: SessionManager, config: Config):
        self._flow = flow
        self._chat = chat
        self._session = session
        self._config = config
        self._persona = "coach" if flow.mode == "guided" else "interviewer"

    def opening(self) -> dict:
        return {
            "title": self._flow.case.meta.title,
            "prompt": self._flow.case.prompt,
            "mode": self._flow.mode,
            "phase": self._flow.phase_name,
            "persona": self._persona,
        }

    def reply_tokens(self, text: str) -> Iterator[str]:
        phase = self._flow.phase_name
        self._flow.record_turn("user", text)
        self._session.record_turn("user", text, phase=phase)
        stream = self._chat(self._flow.context(self._persona))
        parts: list[str] = []
        for tok in stream:
            parts.append(tok)
            yield tok
        reply = "".join(parts)
        self._flow.record_turn("assistant", reply)
        rec = getattr(stream, "record", None)
        self._session.record_turn(
            "assistant",
            reply,
            phase=phase,
            provider=getattr(rec, "provider", None),
            latency_ms=getattr(rec, "latency_ms", None),
        )

    def advance(self) -> dict:
        # The last phase is interactive too (like the CLI): a further advance from
        # it ends the case. `last` lets the UI label the final phase.
        if self._flow.is_terminal:
            return self._end()
        self._flow.advance()
        return {
            "terminal": False,
            "phase": self._flow.phase_name,
            "last": self._flow.is_terminal,
        }

    def _end(self) -> dict:
        out: dict = {
            "terminal": True,
            "model_answer": reveal_model_answer(self._flow.case),
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
                out["feedback"] = assemble_feedback(self._flow.case, card)
        return out


class LiveEngine:
    def __init__(self, config: Config, library, store, chat):
        self._config = config
        self._library = library
        self._store = store
        self._chat = chat
        self._window = config.context.transcript_window_turns
        self._sessions: dict[str, LiveCaseSession] = {}

    def start(self, content_id: str, mode: str) -> str:
        case = self._library.cases[content_id]  # KeyError -> 404 upstream
        flow = CaseFlow(case, mode=mode, transcript_window_turns=self._window)
        session = SessionManager(
            self._store, content_id=content_id, content_type="case", mode=mode
        )
        sid = uuid4().hex
        self._sessions[sid] = LiveCaseSession(flow, self._chat, session, self._config)
        return sid

    def get(self, session_id: str) -> LiveCaseSession:
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
