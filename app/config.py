"""Load and validate config.yaml + .env (04_ENGINEERING_RULES §7).

The config object holds the *name* of each provider's API-key env var, never the
key value, so secrets cannot leak through logs or reprs.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


class ConfigError(Exception):
    """Raised on unreadable, malformed, or invalid configuration."""


class ProviderConfig(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str | None = None

    def api_key(self) -> str | None:
        """Resolve the key from the environment at call time (never stored)."""
        return os.environ.get(self.api_key_env) if self.api_key_env else None


class SttConfig(BaseModel):
    base_url: str
    model: str
    api_key_env: str | None = None

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None


class RetryConfig(BaseModel):
    max_retries: int = 2
    backoff_base_s: float = 1.0
    request_timeout_s: float = 30.0


class ContextConfig(BaseModel):
    transcript_window_turns: int = 12
    transcript_window_tokens: int = 2000


class LadderConfig(BaseModel):
    graduation_min_avg: float = 3.0
    hidden_score_sessions: int = 3


class Config(BaseModel):
    offline: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    providers: list[ProviderConfig]
    stt: SttConfig
    retry: RetryConfig = RetryConfig()
    context: ContextConfig = ContextConfig()
    voice: str
    score_visibility: bool = False
    ladder: LadderConfig = LadderConfig()

    def provider(self, name: str) -> ProviderConfig:
        for p in self.providers:
            if p.name == name:
                return p
        raise KeyError(f"no provider named {name!r}")


def load_config(path: str | Path = "config.yaml") -> Config:
    """Parse and validate config, loading .env first. Fails fast and readably."""
    load_dotenv()
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"malformed YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} is not a mapping")
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config in {path}:\n{e}") from e
