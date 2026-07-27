"""T-040 acceptance: a typed case runs over HTTP with streamed tokens through the
real LiveEngine (loader/router/store), driven by a fake chat seam (no network)."""

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import load_config
from app.db.store import Store
from app.engine.content_models import Case
from app.main import LiveEngine, create_app

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"


def _case() -> Case:
    return Case.model_validate(
        json.loads((FIXT / "cases" / "case-cement-profitability.json").read_text())
    )


def _fake_chat():
    class Stream:
        record = SimpleNamespace(provider="groq", latency_ms=1.0, ratelimit={})

        def __iter__(self):
            yield from ["Tell ", "me ", "more."]

    return lambda messages: Stream()


def _reassemble(sse_text: str) -> str:
    tokens = []
    for evt in sse_text.split("\n\n"):
        line = next((x for x in evt.splitlines() if x.startswith("data:")), None)
        if line:
            payload = line[len("data:") :].strip()
            if payload != "[DONE]":
                tokens.append(json.loads(payload)["token"])
    return "".join(tokens)


def test_typed_case_runs_over_http_end_to_end():
    case = _case()
    store = Store(":memory:")
    library = SimpleNamespace(cases={case.meta.id: case})
    engine = LiveEngine(load_config(), library, store, _fake_chat())
    client = TestClient(create_app(engine))

    opened = client.post("/api/session", json={"content_id": case.meta.id}).json()
    sid = opened["session_id"]
    assert opened["prompt"] == case.prompt and opened["persona"] == "interviewer"

    resp = client.post(f"/api/session/{sid}/message", json={"text": "why did it fall?"})
    assert _reassemble(resp.text) == "Tell me more."  # tokens streamed + reassembled

    # the exchange is persisted server-side (backend owns state)
    turns = store.get_turns(1)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[1]["provider"] == "groq"

    # walk phases to the terminal reveal
    for _ in range(6):
        data = client.post(f"/api/session/{sid}/advance").json()
        if data.get("terminal"):
            break
    assert data["terminal"]
    assert case.model_answer.recommendation in data["model_answer"]  # verbatim reveal
