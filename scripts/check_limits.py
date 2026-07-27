#!/usr/bin/env python3
"""Per-provider rate-limit headroom (T-066, Phase 5).

Fires one tiny streamed request at each configured chat provider and prints the
remaining-* rate-limit headers it returns — a quick pre-session check that you
have budget left before starting a case. API keys are never printed: only the
provider name and the ratelimit header values reach the output.

    python scripts/check_limits.py

The header extraction and formatting are pure and unit-tested; the probe touches
the network and is run by hand.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass(frozen=True)
class LimitRow:
    provider: str
    remaining: dict[str, str]  # header -> value (already key-free)
    error: str | None


# --- pure output (unit-tested) ----------------------------------------------


def remaining_headroom(ratelimit: dict[str, str]) -> dict[str, str]:
    """Keep only the remaining-* headers (e.g. remaining-requests/-tokens)."""
    return {k: v for k, v in ratelimit.items() if "remaining" in k.lower()}


def _label(header: str) -> str:
    return header.lower().replace("x-ratelimit-remaining-", "")


def _line(row: LimitRow) -> str:
    if row.error:
        return f"{row.provider:12} —  ({row.error})"
    if not row.remaining:
        return f"{row.provider:12} (no ratelimit headers returned)"
    parts = ", ".join(f"{_label(k)}: {v}" for k, v in row.remaining.items())
    return f"{row.provider:12} {parts}"


def format_limits(rows: list[LimitRow]) -> str:
    return "\n".join(_line(r) for r in rows)


# --- probe (network) --------------------------------------------------------


def probe(provider, *, client_factory=None) -> LimitRow:
    from app.providers.llm_client import ChatClient

    factory = client_factory or ChatClient
    if provider.api_key_env and not provider.api_key():
        return LimitRow(provider.name, {}, f"missing {provider.api_key_env}")
    try:
        stream = factory(provider).stream([{"role": "user", "content": "ping"}])
        list(stream)  # exhaust so the ratelimit headers land on the record
    except Exception as e:  # noqa: BLE001 - report every failure class, key-free
        return LimitRow(provider.name, {}, type(e).__name__)
    return LimitRow(
        provider.name, remaining_headroom(stream.record.ratelimit or {}), None
    )


def main(argv: list[str]) -> int:
    from app.config import load_config

    config = load_config()
    rows = [probe(p) for p in config.providers]
    print(format_limits(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
