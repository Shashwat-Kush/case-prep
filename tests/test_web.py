"""T-040: FastAPI transport contract tests against a fake engine, plus SSE
stream reassembly. The live engine (LiveEngine) is exercised end to end in
test_web_live.py; here the engine is a stub so we test the HTTP/SSE contract only.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeSession:
    def __init__(self):
        self._advances = iter(
            [
                {"terminal": False, "phase": "structuring"},
                {"terminal": True, "model_answer": "MODEL", "feedback": "FB"},
            ]
        )

    def opening(self):
        return {"title": "T", "prompt": "P", "mode": "standard", "phase": "opening"}

    def reply_tokens(self, text):
        yield from ["Hel", "lo ", "world"]

    def advance(self):
        return next(self._advances)


class FakeEngine:
    def __init__(self):
        self._sessions = {}

    def start(self, content_id, mode):
        if content_id == "nope":
            raise KeyError(content_id)
        sid = f"sid-{len(self._sessions)}"
        self._sessions[sid] = FakeSession()
        return sid

    def get(self, session_id):
        return self._sessions[session_id]  # KeyError -> 404


@pytest.fixture
def client():
    return TestClient(create_app(FakeEngine()))


def _reassemble(sse_text: str) -> tuple[str, bool]:
    """Collapse an SSE body into the joined tokens and whether [DONE] arrived."""
    tokens, done = [], False
    for evt in sse_text.split("\n\n"):
        line = next((x for x in evt.splitlines() if x.startswith("data:")), None)
        if not line:
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            done = True
        else:
            tokens.append(json.loads(payload)["token"])
    return "".join(tokens), done


def test_create_session_returns_id_and_opening(client):
    r = client.post("/api/session", json={"content_id": "case-x", "mode": "standard"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] and body["prompt"] == "P" and body["phase"] == "opening"


def test_unknown_content_id_is_404(client):
    r = client.post("/api/session", json={"content_id": "nope"})
    assert r.status_code == 404


def test_message_streams_tokens_and_reassembles(client):
    sid = client.post("/api/session", json={"content_id": "c"}).json()["session_id"]
    r = client.post(f"/api/session/{sid}/message", json={"text": "hi"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    text, done = _reassemble(r.text)
    assert text == "Hello world" and done  # tokens reassembled, stream terminated


def test_message_on_unknown_session_is_404(client):
    r = client.post("/api/session/ghost/message", json={"text": "hi"})
    assert r.status_code == 404


def test_advance_walks_phase_then_terminal_with_reveal(client):
    sid = client.post("/api/session", json={"content_id": "c"}).json()["session_id"]
    first = client.post(f"/api/session/{sid}/advance").json()
    assert first == {"terminal": False, "phase": "structuring"}
    end = client.post(f"/api/session/{sid}/advance").json()
    assert end["terminal"] and end["model_answer"] == "MODEL"


def test_index_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "CasePrep Local" in r.text
