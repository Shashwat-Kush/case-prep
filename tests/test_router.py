import logging
from types import SimpleNamespace

import httpx
import pytest

from app.config import ProviderConfig
from app.providers.llm_client import ChatClient
from app.providers.router import Router, RouterError

SSE = (
    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'
    b"data: [DONE]\n\n"
)
RL = {"retry-after": "2"}
MSGS = [{"role": "user", "content": "hi"}]

GROQ = ProviderConfig(name="groq", base_url="http://g/v1", model="m", api_key_env="K1")
NVIDIA = ProviderConfig(
    name="nvidia", base_url="http://n/v1", model="m", api_key_env="K2"
)
OLLAMA = ProviderConfig(name="ollama", base_url="http://127.0.0.1/v1", model="m")
PROVIDERS = [GROQ, NVIDIA, OLLAMA]


def _clock():
    t = {"v": 0.0}

    def now():
        t["v"] += 0.1
        return t["v"]

    return now


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(request):
    return httpx.Response(200, headers=RL, content=SSE)


def _always(status, headers=None):
    def handler(request):
        return httpx.Response(status, headers=headers or {}, content=b'{"error":"x"}')

    return handler


def _flaky(status, headers=None, n=1):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= n:
            return httpx.Response(status, headers=headers or {}, content=b'{"e":1}')
        return httpx.Response(200, headers=RL, content=SSE)

    return handler


def _refused(request):
    raise httpx.ConnectError("connection refused")


def _router(handlers, *, offline=False, seen=None):
    slept: list[float] = []

    def factory(p):
        if seen is not None:
            seen.append(p.name)
        return ChatClient(p, client=_client(handlers[p.name]), now=_clock())

    cfg = SimpleNamespace(
        providers=PROVIDERS,
        offline=offline,
        retry=SimpleNamespace(max_retries=2, backoff_base_s=1.0),
    )
    router = Router(cfg, client_factory=factory, sleep=slept.append, rand=lambda: 0.0)
    return router, slept


def test_429_with_retry_after_waits_exactly_then_succeeds():
    router, slept = _router(
        {"groq": _flaky(429, RL, n=1), "nvidia": _ok, "ollama": _ok}
    )
    stream = router.chat(MSGS)
    assert stream.text() == "Hello world"
    assert stream.record.provider == "groq"  # same provider after honored wait
    assert slept == [2.0]  # exact retry-after, no backoff math


def test_retries_exhausted_fails_over_to_next_provider():
    router, slept = _router({"groq": _always(500), "nvidia": _ok, "ollama": _ok})
    stream = router.chat(MSGS)
    assert stream.text() == "Hello world"
    assert stream.record.provider == "nvidia"
    assert slept == [1.0, 2.0]  # 2 backoffs (base*2^attempt, jitter=0), then failover


def test_connection_refused_fails_over_without_backoff():
    router, slept = _router({"groq": _refused, "nvidia": _ok, "ollama": _ok})
    stream = router.chat(MSGS)
    assert stream.text() == "Hello world"
    assert stream.record.provider == "nvidia"
    assert slept == []  # connection refused -> immediate failover, no retry


def test_auth_failure_surfaces_once_per_session_then_fails_over(caplog):
    router, _ = _router({"groq": _always(401), "nvidia": _ok, "ollama": _ok})
    with caplog.at_level(logging.ERROR, logger="app.providers.router"):
        s1 = router.chat(MSGS)
        assert s1.text() == "Hello world" and s1.record.provider == "nvidia"
        router.chat(MSGS).text()  # second turn, same session
    auth = [r for r in caplog.records if "auth failure on groq" in r.getMessage()]
    assert len(auth) == 1  # surfaced once per session, not per turn


def test_invalid_request_is_fatal_and_does_not_fail_over():
    seen: list[str] = []
    router, _ = _router({"groq": _always(400), "nvidia": _ok, "ollama": _ok}, seen=seen)
    with pytest.raises(RouterError):
        router.chat(MSGS).text()
    assert "nvidia" not in seen  # fatal-for-turn: no silent failover


def test_offline_uses_only_local_provider_and_never_calls_cloud():
    seen: list[str] = []
    router, _ = _router(
        {"groq": _ok, "nvidia": _ok, "ollama": _ok}, offline=True, seen=seen
    )
    stream = router.chat(MSGS)
    assert stream.text() == "Hello world"
    assert stream.record.provider == "ollama"
    assert seen == ["ollama"]  # cloud providers never constructed -> zero cloud calls


def _ok_with_headroom(request):
    headers = {**RL, "x-ratelimit-remaining-requests": "42"}
    return httpx.Response(200, headers=headers, content=SSE)


def test_status_reports_no_provider_before_any_call():
    router, _ = _router({"groq": _ok, "nvidia": _ok, "ollama": _ok})
    st = router.status()
    assert st["provider"] is None and st["primary"] == "groq"


def test_status_reflects_serving_provider_and_updates_on_failover():
    router, _ = _router(
        {"groq": _always(500), "nvidia": _ok_with_headroom, "ollama": _ok}
    )
    router.chat(MSGS).text()  # groq exhausts retries, nvidia serves
    st = router.status()
    assert st["provider"] == "nvidia"  # indicator follows the failover
    assert st["primary"] == "groq"
    assert st["ratelimit"]["x-ratelimit-remaining-requests"] == "42"  # headroom


def test_all_providers_failing_raises_router_error():
    router, _ = _router(
        {"groq": _always(500), "nvidia": _always(500), "ollama": _always(500)}
    )
    with pytest.raises(RouterError, match="all providers failed"):
        router.chat(MSGS).text()
