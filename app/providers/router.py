"""Provider router (02_ARCHITECTURE §3, 04_ENGINEERING_RULES §5). Walks the
configured provider chain, implementing the error taxonomy exactly:

  Retryable      429 (honor retry-after exactly, else exp. backoff + jitter),
                 transient network, 5xx -> retry same provider, max 2 tries.
  Failover       retries exhausted, connection refused -> next provider.
  Fatal-for-turn invalid request / auth (401,403) -> surface once, no silent
                 retry; auth then fails over (rule: surface once per session).

The chat stream is lazy: HTTP status and connection errors surface on the first
token, so the router *primes* each provider (pulls one token) to classify before
committing, then re-yields that token. offline mode restricts the chain to local
(keyless) providers, so cloud is never touched.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

from app.config import Config, ProviderConfig
from app.providers.llm_client import ChatClient, LLMError

log = logging.getLogger(__name__)


class RouterError(Exception):
    """No provider could serve the turn (all failed or none eligible)."""


def _retry_after(record) -> float | None:
    """The retry-after header (seconds) captured on the failed call, if any."""
    for k, v in (getattr(record, "ratelimit", {}) or {}).items():
        if k.lower() == "retry-after":
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


class _RoutedStream:
    """Iterable of tokens; `record` points at the serving provider's telemetry
    once iteration has started (mirrors ChatStream so callers are unchanged)."""

    def __init__(self, start: Callable[[_RoutedStream], object]):
        self.record = None
        self._it = start(self)

    def __iter__(self):
        return self._it

    def text(self) -> str:
        return "".join(self._it)


class Router:
    def __init__(
        self,
        config: Config,
        *,
        client_factory: Callable[[ProviderConfig], ChatClient] = ChatClient,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ):
        if not config.providers:
            raise ValueError("no providers configured")
        self._providers = config.providers
        self._factory = client_factory
        self._sleep = sleep
        self._rand = rand
        self._offline = bool(getattr(config, "offline", False))
        retry = getattr(config, "retry", None)
        self._max_retries = int(getattr(retry, "max_retries", 2))
        self._backoff_base = float(getattr(retry, "backoff_base_s", 1.0))
        self._auth_surfaced: set[str] = set()
        self._last_provider: str | None = None
        self._last_ratelimit: dict[str, str] = {}

    @property
    def primary(self) -> ProviderConfig:
        return self._providers[0]

    def status(self) -> dict:
        """Live routing state for the UI: which provider last served and its
        remaining headroom (T-044). `provider` is None until the first call."""
        return {
            "provider": self._last_provider,
            "primary": self.primary.name,
            "offline": self._offline,
            "ratelimit": dict(self._last_ratelimit),
        }

    def _eligible(self) -> list[ProviderConfig]:
        """Offline uses only local (keyless) providers; cloud is never called."""
        if self._offline:
            return [p for p in self._providers if p.api_key_env is None]
        return list(self._providers)

    def chat(self, messages: list[dict], **params) -> _RoutedStream:
        return _RoutedStream(lambda routed: self._iterate(messages, params, routed))

    def _classify(self, exc: Exception, record) -> tuple[str, float | None]:
        """Map an exception to (action, wait). action: retry|failover|auth|fatal."""
        if isinstance(exc, LLMError):
            s = exc.status
            if s == 429:
                return "retry", _retry_after(record)
            if s is not None and 500 <= s < 600:
                return "retry", None
            if s in (401, 403):
                return "auth", None  # surface once, then failover
            return "fatal", None  # invalid request / other 4xx: fatal for turn
        if isinstance(exc, httpx.ConnectError):
            return "failover", None  # connection refused
        if isinstance(exc, httpx.HTTPError):
            return "retry", None  # timeouts / transient network
        return "fatal", None

    def _backoff(self, wait: float | None, attempt: int) -> None:
        if wait is not None:  # honor retry-after exactly
            self._sleep(wait)
            return
        base = self._backoff_base * (2**attempt)
        self._sleep(base + self._rand() * base)  # exponential + jitter

    def _surface_auth(self, p: ProviderConfig, exc: LLMError) -> None:
        if p.name not in self._auth_surfaced:  # once per session
            self._auth_surfaced.add(p.name)
            log.error("auth failure on %s: %s — failing over", p.name, exc)

    def _iterate(self, messages, params, routed):
        eligible = self._eligible()
        if not eligible:
            raise RouterError("no eligible providers (offline with no local provider)")
        last: Exception | None = None
        for p in eligible:
            for attempt in range(self._max_retries + 1):
                stream = self._factory(p).stream(messages, **params)
                it = iter(stream)
                try:
                    first = next(it)
                except StopIteration:
                    routed.record = stream.record  # empty but successful
                    return
                except (LLMError, httpx.HTTPError) as exc:
                    last = exc
                    action, wait = self._classify(exc, stream.record)
                    if action == "retry" and attempt < self._max_retries:
                        log.info("provider %s retry %d: %s", p.name, attempt + 1, exc)
                        self._backoff(wait, attempt)
                        continue
                    if action == "fatal":
                        raise RouterError(f"{p.name}: {exc}") from exc
                    if action == "auth":
                        self._surface_auth(p, exc)
                    else:
                        log.info("failover from %s: %s", p.name, exc)
                    break  # next provider
                else:
                    routed.record = stream.record
                    self._last_provider = p.name
                    self._last_ratelimit = dict(
                        getattr(stream.record, "ratelimit", {}) or {}
                    )
                    log.info("provider %s serving turn", p.name)
                    yield first
                    yield from it
                    return
        raise RouterError("all providers failed") from last
