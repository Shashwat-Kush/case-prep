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


def _scoring_chat(evidence):
    """Fake chat that answers conversation turns with filler but returns a valid
    scorecard JSON (all five dims, given evidence quotes) on scoring calls."""
    payload = json.dumps(
        {"scores": {d: {"score": 4, "evidence": q} for d, q in evidence.items()}}
    )

    class Stream:
        record = SimpleNamespace(provider="groq", latency_ms=1.0, ratelimit={})

        def __init__(self, toks):
            self._toks = toks

        def __iter__(self):
            yield from self._toks

    def chat(messages):
        scoring = any("scoring engine" in m["content"] for m in messages)
        return Stream([payload] if scoring else ["Tell ", "me ", "more."])

    return chat


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

    assert "time_budget_s" in opened  # per-phase budget exposed for the UI timer

    for _ in range(6):
        state = _act(client, sid, "advance")
        if state.get("done"):
            break
    assert state["done"] and state["model_answer"]
    assert isinstance(state["overruns"], list)  # pacing summary in the end payload


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


def test_exhibit_gated_until_unlocked_then_serves_data():
    client, _ = _client()
    sid = _start(client, "case-cement-profitability")["session_id"]
    ex = "ex-cost-breakdown"  # unlock_condition: phase:analysis

    # locked in the opening phase -> data never leaves the backend
    assert client.get(f"/api/session/{sid}/exhibit/{ex}").status_code == 403
    assert client.get(f"/api/session/{sid}/exhibit/nope").status_code == 404

    # walking to the analysis phase auto-unlocks it
    state = _act(client, sid, "advance")
    while ex not in state.get("exhibits", []):
        state = _act(client, sid, "advance")
    r = client.get(f"/api/session/{sid}/exhibit/{ex}")
    assert r.status_code == 200
    assert r.json()["data"] == {"power": 400, "freight": 500, "other": 300}


def test_intent_unlock_action_exposes_exhibit():
    client, _ = _client()
    sid = _start(client, "case-cement-profitability")["session_id"]
    ex = "ex-cost-breakdown"
    state = _act(client, sid, "exhibit", ex)  # explicit unlock, before analysis
    assert ex in state["exhibits"]
    assert client.get(f"/api/session/{sid}/exhibit/{ex}").status_code == 200


def test_non_case_session_has_no_exhibits():
    client, _ = _client()
    sid = _start(client, "lesson-profitability")["session_id"]
    assert client.get(f"/api/session/{sid}/exhibit/x").status_code == 404


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


def _to_estimation(client, sid):
    state = _act(client, sid, "advance")
    while state["step"] != "estimation":
        state = _act(client, sid, "advance")
    return state


def test_coached_estimate_returns_inline_verification():
    # delhi_pop = 20,000,000 with zero tolerance: an exact hit verifies, a value
    # above it fails with a "high" direction hint (T-045 acceptance).
    client, _ = _client()
    sid = _start(client, "guess-petrol-pumps-delhi", mode="coached")["session_id"]
    _to_estimation(client, sid)
    ok = _act(client, sid, "estimate", "20000000")
    assert ok["check"] == {"segment": "delhi_pop", "ok": True, "direction": None}


def test_coached_estimate_flags_wrong_step_with_direction():
    client, _ = _client()
    sid = _start(client, "guess-petrol-pumps-delhi", mode="coached")["session_id"]
    _to_estimation(client, sid)
    bad = _act(client, sid, "estimate", "30000000")
    assert bad["check"] == {"segment": "delhi_pop", "ok": False, "direction": "high"}


def test_timed_guesstimate_has_no_inline_check():
    client, _ = _client()
    sid = _start(client, "guess-petrol-pumps-delhi", mode="timed")["session_id"]
    _to_estimation(client, sid)
    state = _act(client, sid, "estimate", "30000000")
    assert "check" not in state


def test_review_links_scorecard_quotes_to_transcript_turns():
    # Evidence quotes are substrings of real user turns; the review must resolve
    # each quote to the id of the turn it came from (T-046 acceptance).
    store = Store(":memory:")
    evidence = {
        "structure": ["revenue is falling"],
        "math": ["costs rose"],
        "judgment": ["revenue is falling"],
        "communication": ["costs rose"],
        "synthesis": ["revenue is falling"],
    }
    engine = LiveEngine(load_config(), _library(), store, _scoring_chat(evidence))
    client = TestClient(create_app(engine))
    sid = _start(client, "case-cement-profitability")["session_id"]
    client.post(f"/api/session/{sid}/message", json={"text": "our revenue is falling"})
    client.post(f"/api/session/{sid}/message", json={"text": "costs rose sharply"})
    state = {}
    for _ in range(8):
        state = _act(client, sid, "advance")
        if state.get("done"):
            break
    assert state["done"]

    review = client.get(f"/api/session/{sid}/review").json()
    assert review["average"] == 4.0
    text_by_id = {t["id"]: t["text"] for t in review["transcript"]}
    by_dim = {s["dimension"]: s for s in review["scores"]}
    for dim in evidence:
        for e in by_dim[dim]["evidence"]:
            assert e["turn_id"] is not None
            assert e["quote"] in text_by_id[e["turn_id"]]


def test_audio_endpoint_accepts_upload_and_degrades_without_stt():
    # Push-to-talk (T-050): the raw blob reaches the backend. With STT unwired the
    # response degrades to typed (transcript None) per 04 §5 Degrade.
    client, _ = _client()
    sid = _start(client, "case-cement-profitability")["session_id"]
    r = client.post(f"/api/session/{sid}/audio", content=b"\x1a\x45\xdf\xa3fakewebm")
    assert r.status_code == 200
    assert r.json() == {
        "bytes": 12,
        "transcript": None,
        "degraded": True,
        "numbers": [],
    }


def test_audio_endpoint_returns_transcript_when_stt_wired():
    from app.providers.stt_client import Transcription

    store = Store(":memory:")
    engine = LiveEngine(
        load_config(),
        _library(),
        store,
        _fake_chat(),
        transcribe=lambda audio: Transcription(True, "revenue is fifteen crore", 12.0),
    )
    client = TestClient(create_app(engine))
    sid = _start(client, "case-cement-profitability")["session_id"]
    r = client.post(f"/api/session/{sid}/audio", content=b"blob").json()
    assert r["degraded"] is False
    assert r["transcript"] == "revenue is 150000000"  # number-cleaned
    # the spoken number is surfaced for confirmation with its teen/ty alternate
    assert r["numbers"] == [
        {
            "surface": "fifteen crore",
            "value": 150000000.0,
            "candidates": [150000000.0, 500000000.0],
        }
    ]


def test_audio_endpoint_rejects_empty_upload():
    client, _ = _client()
    sid = _start(client, "case-cement-profitability")["session_id"]
    assert client.post(f"/api/session/{sid}/audio", content=b"").status_code == 400


def test_non_case_session_has_no_review():
    client, _ = _client()
    sid = _start(client, "lesson-profitability")["session_id"]
    assert client.get(f"/api/session/{sid}/review").status_code == 404


def test_coached_completion_reports_final_range_check():
    client, _ = _client()
    sid = _start(client, "guess-petrol-pumps-delhi", mode="coached")["session_id"]
    state = _to_estimation(client, sid)
    while state["step"] == "estimation":
        state = _act(client, sid, "estimate", "600")  # last estimate = final answer
    while not state.get("done"):
        state = _act(client, sid, "advance")
    fc = state["final_check"]
    assert fc["value"] == 600 and fc["low"] == 400 and fc["high"] == 800
    assert fc["in_range"] is True
