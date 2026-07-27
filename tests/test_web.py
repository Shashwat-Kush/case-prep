"""T-040/T-041: FastAPI transport contract tests against a fake engine, plus SSE
stream reassembly. The live engine is exercised end to end in test_web_live.py.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeSession:
    def __init__(self):
        self._steps = iter(
            [
                {"type": "case", "done": False, "phase": "structuring"},
                {"type": "case", "done": True, "model_answer": "MODEL"},
            ]
        )

    def state(self):
        return {"type": "case", "done": False, "phase": "opening", "prompt": "P"}

    def reply_tokens(self, text):
        yield from ["Hel", "lo ", "world"]

    def act(self, action, value):
        if action == "advance":
            return next(self._steps)
        return {"echoed": action, "value": value}


class FakeEngine:
    def __init__(self):
        self._sessions = {}

    def content_list(self):
        return {
            "cases": [{"id": "case-x", "title": "X", "modes": ["standard", "guided"]}],
            "lessons": [{"id": "lesson-y", "title": "Y"}],
            "guesstimates": [{"id": "guess-z", "title": "Z", "modes": ["coached"]}],
        }

    def start(self, content_id, mode):
        if content_id == "nope":
            raise KeyError(content_id)
        sid = f"sid-{len(self._sessions)}"
        self._sessions[sid] = FakeSession()
        return sid

    def get(self, session_id):
        return self._sessions[session_id]  # KeyError -> 404

    def status(self):
        return {"provider": "groq", "primary": "groq", "ratelimit": {"x": "5"}}

    def transcribe(self, audio):
        return {"transcript": None, "degraded": True}

    def speak(self, sentence):
        return None


@pytest.fixture
def client():
    return TestClient(create_app(FakeEngine()))


def _reassemble(sse_text: str) -> tuple[str, bool]:
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


def test_content_list_groups_all_three_types(client):
    body = client.get("/api/content").json()
    assert [c["id"] for c in body["cases"]] == ["case-x"]
    assert body["lessons"][0]["id"] == "lesson-y"
    assert body["guesstimates"][0]["modes"] == ["coached"]


def test_create_session_returns_id_and_state(client):
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
    assert text == "Hello world" and done


def test_message_on_unknown_session_is_404(client):
    r = client.post("/api/session/ghost/message", json={"text": "hi"})
    assert r.status_code == 404


def test_action_advance_walks_to_terminal(client):
    sid = client.post("/api/session", json={"content_id": "c"}).json()["session_id"]
    first = client.post(f"/api/session/{sid}/action", json={"action": "advance"}).json()
    assert first["phase"] == "structuring" and not first["done"]
    end = client.post(f"/api/session/{sid}/action", json={"action": "advance"}).json()
    assert end["done"] and end["model_answer"] == "MODEL"


def test_index_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "CasePrep Local" in r.text


def test_status_endpoint_reflects_engine_state(client):
    body = client.get("/api/status").json()
    assert body["provider"] == "groq" and body["ratelimit"] == {"x": "5"}
