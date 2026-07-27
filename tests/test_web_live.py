"""T-040/T-041 acceptance: a typed case, a lesson, and a coached guesstimate each
run to completion over HTTP through the real LiveEngine (loader/router/store),
driven by a fake chat seam (no network).
"""

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import load_config
from app.db.store import Store
from app.engine.content_models import Case, Guesstimate, Lesson
from app.main import LiveEngine, create_app

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"


def _load(model, rel):
    return model.model_validate(json.loads((FIXT / rel).read_text()))


def _library():
    case = _load(Case, "cases/case-cement-profitability.json")
    lesson = _load(Lesson, "lessons/lesson-profitability.json")
    guess = _load(Guesstimate, "guesstimates/guess-petrol-pumps-delhi.json")
    return SimpleNamespace(
        cases={case.meta.id: case},
        lessons={lesson.meta.id: lesson},
        guesstimates={guess.meta.id: guess},
    )


def _fake_chat():
    class Stream:
        record = SimpleNamespace(provider="groq", latency_ms=1.0, ratelimit={})

        def __iter__(self):
            yield from ["Tell ", "me ", "more."]

    return lambda messages: Stream()


def _client():
    store = Store(":memory:")
    engine = LiveEngine(load_config(), _library(), store, _fake_chat())
    return TestClient(create_app(engine)), store


def _reassemble(sse_text: str) -> str:
    tokens = []
    for evt in sse_text.split("\n\n"):
        line = next((x for x in evt.splitlines() if x.startswith("data:")), None)
        if line:
            payload = line[len("data:") :].strip()
            if payload != "[DONE]":
                tokens.append(json.loads(payload)["token"])
    return "".join(tokens)


def _start(client, content_id, mode="standard"):
    r = client.post("/api/session", json={"content_id": content_id, "mode": mode})
    return r.json()


def _act(client, sid, action, value=None):
    return client.post(
        f"/api/session/{sid}/action", json={"action": action, "value": value}
    ).json()


def test_typed_case_runs_over_http_end_to_end():
    client, store = _client()
    opened = _start(client, "case-cement-profitability")
    sid = opened["session_id"]
    assert opened["prompt"] and opened["persona"] == "interviewer"

    resp = client.post(f"/api/session/{sid}/message", json={"text": "why?"})
    assert _reassemble(resp.text) == "Tell me more."

    turns = store.get_turns(1)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[1]["provider"] == "groq"

    for _ in range(6):
        state = _act(client, sid, "advance")
        if state.get("done"):
            break
    assert state["done"] and state["model_answer"]


def test_guided_case_coaching_and_reveal_gate():
    client, _ = _client()
    opened = _start(client, "case-cement-profitability", mode="guided")
    sid = opened["session_id"]
    assert opened["persona"] == "coach"

    # advance to the phase that carries a coaching block (analysis)
    state = _act(client, sid, "advance")
    while "coaching" not in state:
        state = _act(client, sid, "advance")
    assert state["coaching"] and state["attempted"] is False

    blocked = _act(client, sid, "reveal")  # before any attempt
    assert "error" in blocked and "attempted" in blocked["error"]

    client.post(f"/api/session/{sid}/message", json={"text": "my attempt"})
    revealed = _act(client, sid, "reveal")
    assert revealed.get("coach_reveal")


def test_lesson_runs_teaching_quiz_to_completion():
    client, _ = _client()
    sid = _start(client, "lesson-profitability")["session_id"]
    # walk teaching sections until the quiz appears
    state = _act(client, sid, "advance")
    while state["stage"] == "teaching":
        state = _act(client, sid, "advance")
    assert state["stage"] == "quiz"
    first_answer = state["options"][0] if state["options"] else "x"
    graded = _act(client, sid, "answer", first_answer)
    assert "correct" in graded and "explanation" in graded
    # keep answering until complete
    while not graded.get("done"):
        opts = graded.get("options") or ["x"]
        graded = _act(client, sid, "answer", opts[0])
    assert graded["stage"] == "complete" and "coverage" in graded


def test_coached_guesstimate_runs_all_steps_to_completion():
    client, _ = _client()
    sid = _start(client, "guess-petrol-pumps-delhi", mode="coached")["session_id"]
    state = _start_step = _act(client, sid, "advance")  # clarify -> approach
    # advance until estimation
    while state["step"] not in ("estimation", "complete"):
        state = _act(client, sid, "advance")
    assert state["step"] == "estimation" and state["segment"]
    # submit an estimate per segment until we leave estimation
    while state["step"] == "estimation":
        state = _act(client, sid, "estimate", "10")
    # advance through any remaining steps to completion
    while not state.get("done"):
        state = _act(client, sid, "advance")
    assert state["done"] and state["estimates"]
