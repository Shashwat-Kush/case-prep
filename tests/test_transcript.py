import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import run_case
from app.db.store import Store
from app.engine.case_flow import CaseFlow
from app.engine.content_models import Case
from app.engine.session_manager import SessionManager

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"


def _case() -> Case:
    return Case.model_validate(
        json.loads((FIXT / "cases" / "case-cement-profitability.json").read_text())
    )


def _fake_chat(reply: str = "Understood."):
    """Yields tokens and carries a telemetry record like the real ChatStream."""

    class Stream:
        record = SimpleNamespace(provider="groq", latency_ms=123.4)

        def __iter__(self):
            for word in reply.split():
                yield word + " "

    return lambda messages: Stream()


def _reader(lines):
    it = iter(lines)
    return lambda: next(it)


@pytest.fixture
def store() -> Store:
    s = Store(":memory:")
    yield s
    s.close()


def test_completed_case_yields_ordered_transcript_with_provider_latency(store: Store):
    flow = CaseFlow(_case())  # standard: opening, structuring, analysis, synthesis
    session = SessionManager(
        store,
        content_id="case-cement-profitability",
        content_type="case",
        mode="standard",
    )
    # one user turn in opening, then walk to terminal
    lines = ["why did profit fall?", "/next", "/next", "/next", "/next"]
    run_case(
        flow,
        _fake_chat("Let us look at costs."),
        _reader(lines),
        lambda _: None,
        session,
    )
    session.end()

    turns = store.get_turns(session.session_id)
    roles = [(t["role"], t["phase"]) for t in turns]
    # user question + its assistant reply in opening, then the end-of-case feedback
    assert roles == [
        ("user", "opening"),
        ("assistant", "opening"),
        ("assistant", "feedback"),
    ]
    for a in [t for t in turns if t["role"] == "assistant"]:
        assert a["provider"] == "groq"
        assert a["latency_ms"] == 123.4
    assert turns[0]["text"] == "why did profit fall?"
    assert store.get_session(session.session_id)["ended_at"] is not None


def test_user_turn_has_no_provider_or_latency(store: Store):
    flow = CaseFlow(_case())
    session = SessionManager(store, content_id="case-x", content_type="case")
    run_case(
        flow,
        _fake_chat(),
        _reader(["hi", "/next", "/next", "/next", "/next"]),
        lambda _: None,
        session,
    )
    user_turn = store.get_turns(session.session_id)[0]
    assert user_turn["role"] == "user"
    assert user_turn["provider"] is None
    assert user_turn["latency_ms"] is None
