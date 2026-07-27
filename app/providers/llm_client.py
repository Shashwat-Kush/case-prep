"""OpenAI-compatible streaming chat client (02_ARCHITECTURE §3). All three
providers speak this wire format, so one client covers them via a swappable
base_url/model/key. The OpenAI request/SSE shape lives only in this module
(04 §rule: no provider specifics outside app/providers/).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx

from app.config import ProviderConfig


@dataclass
class CallRecord:
    """Per-call telemetry, filled as the stream is consumed. Token counts and
    latency_ms are complete only once the token iterator is exhausted."""

    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    ttft_ms: float | None = None  # time to first content token
    latency_ms: float | None = None  # total wall time
    finish_reason: str | None = None
    ratelimit: dict[str, str] = field(
        default_factory=dict
    )  # x-ratelimit-*, retry-after


class LLMError(Exception):
    def __init__(self, message: str, *, provider: str, status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status = status


class ChatStream:
    """Iterable of content-delta strings; `record` is complete after iteration."""

    def __init__(self, tokens: Iterator[str], record: CallRecord):
        self._tokens = tokens
        self.record = record

    def __iter__(self) -> Iterator[str]:
        return self._tokens

    def text(self) -> str:
        return "".join(self._tokens)


class ChatClient:
    def __init__(
        self,
        provider: ProviderConfig,
        *,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
        now: Callable[[], float] = time.monotonic,
    ):
        self._p = provider
        self._client = client or httpx.Client(timeout=timeout_s)
        self._now = now

    def stream(self, messages: list[dict], **params) -> ChatStream:
        """Start a streaming chat completion. Returns immediately with a
        ChatStream; the HTTP call runs as its tokens are consumed."""
        body = {
            "model": self._p.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            **params,
        }
        headers = {"Content-Type": "application/json"}
        key = self._p.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        record = CallRecord(provider=self._p.name, model=self._p.model)
        url = f"{self._p.base_url}/chat/completions"
        return ChatStream(self._run(url, body, headers, record), record)

    def _run(self, url, body, headers, record: CallRecord) -> Iterator[str]:
        start = self._now()
        with self._client.stream("POST", url, json=body, headers=headers) as resp:
            record.ratelimit = {
                k: v
                for k, v in resp.headers.items()
                if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"
            }
            if resp.status_code >= 400:
                resp.read()
                raise LLMError(
                    f"{self._p.name} returned {resp.status_code}: {resp.text}",
                    provider=self._p.name,
                    status=resp.status_code,
                )
            first = True
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    u = chunk["usage"]
                    record.prompt_tokens = u.get("prompt_tokens")
                    record.completion_tokens = u.get("completion_tokens")
                    record.total_tokens = u.get("total_tokens")
                for choice in chunk.get("choices", []):
                    if choice.get("finish_reason"):
                        record.finish_reason = choice["finish_reason"]
                    delta = choice.get("delta", {}).get("content")
                    if delta:
                        if first:
                            record.ttft_ms = (self._now() - start) * 1000
                            first = False
                        yield delta
        record.latency_ms = (self._now() - start) * 1000
