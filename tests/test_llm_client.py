import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import ProviderConfig
from app.providers.llm_client import ChatClient, LLMError
from app.providers.router import Router

SSE = (
    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'
    b"data: [DONE]\n\n"
)
RL_HEADERS = {"x-ratelimit-remaining-requests": "99", "retry-after": "2"}
PROVIDER = ProviderConfig(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    model="llama-3.3-70b-versatile",
    api_key_env=None,
)


def _clock():
    t = {"v": 0.0}

    def now():
        t["v"] += 0.1
        return t["v"]

    return now


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_handler(request):
    assert request.url.path.endswith("/chat/completions")
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["model"] == PROVIDER.model
    return httpx.Response(200, headers=RL_HEADERS, content=SSE)


def test_happy_path_streams_and_reassembles():
    cc = ChatClient(PROVIDER, client=_client(_ok_handler), now=_clock())
    stream = cc.stream([{"role": "user", "content": "hi"}])
    assert list(stream) == ["Hello", " world"]
    r = stream.record
    assert r.finish_reason == "stop"
    assert (r.prompt_tokens, r.completion_tokens, r.total_tokens) == (10, 2, 12)
    assert r.provider == "groq" and r.model == PROVIDER.model
    assert r.ttft_ms is not None and r.latency_ms is not None


def test_headers_captured():
    cc = ChatClient(PROVIDER, client=_client(_ok_handler), now=_clock())
    stream = cc.stream([{"role": "user", "content": "hi"}])
    assert stream.text() == "Hello world"
    assert stream.record.ratelimit["x-ratelimit-remaining-requests"] == "99"
    assert stream.record.ratelimit["retry-after"] == "2"


def test_error_status_raises_llmerror():
    def handler(request):
        return httpx.Response(401, content=b'{"error":"bad key"}')

    cc = ChatClient(PROVIDER, client=_client(handler))
    with pytest.raises(LLMError) as e:
        list(cc.stream([{"role": "user", "content": "hi"}]))
    assert e.value.status == 401 and e.value.provider == "groq"


def test_router_uses_primary_provider():
    seen = {}

    def factory(p):
        seen["provider"] = p
        return ChatClient(p, client=_client(_ok_handler), now=_clock())

    router = Router(SimpleNamespace(providers=[PROVIDER]), client_factory=factory)
    stream = router.chat([{"role": "user", "content": "hi"}])
    assert stream.text() == "Hello world"
    assert seen["provider"] is PROVIDER


def test_router_requires_providers():
    with pytest.raises(ValueError):
        Router(SimpleNamespace(providers=[]))
