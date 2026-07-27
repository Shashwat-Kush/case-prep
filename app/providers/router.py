"""Provider router (02_ARCHITECTURE §3). This is the single-provider shell:
it selects the primary provider (Groq, first in config order) and returns a
streaming chat. The 429/failover chain across the configured providers is a
later task; keeping it here means callers never change when it lands.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Config, ProviderConfig
from app.providers.llm_client import ChatClient, ChatStream


class Router:
    def __init__(
        self,
        config: Config,
        *,
        client_factory: Callable[[ProviderConfig], ChatClient] = ChatClient,
    ):
        if not config.providers:
            raise ValueError("no providers configured")
        self._providers = config.providers
        self._factory = client_factory

    @property
    def primary(self) -> ProviderConfig:
        return self._providers[0]

    def chat(self, messages: list[dict], **params) -> ChatStream:
        return self._factory(self.primary).stream(messages, **params)
