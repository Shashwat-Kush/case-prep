#!/usr/bin/env python3
"""Chaos-check helper (T-071): report whether each provider base URL is currently
reachable, so you can confirm the network is actually down (or up) while running
the Wi-Fi-kill procedure in docs/chaos-check.md.

    python scripts/chaos_check.py

This only probes reachability (a HEAD with a short timeout); it never sends a
prompt and never prints keys. The degradation assertions themselves live in the
T-028 router tests and the manual procedure. The formatting is unit-tested; the
probe touches the network.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass(frozen=True)
class Reach:
    name: str
    reachable: bool
    detail: str  # status code or error class — never a key


def _line(r: Reach) -> str:
    mark = "UP  " if r.reachable else "DOWN"
    return f"{mark}  {r.name:10} {r.detail}"


def format_reachability(rows: list[Reach]) -> str:
    return "\n".join(_line(r) for r in rows)


def probe(name: str, base_url: str, *, get=None) -> Reach:
    import httpx

    do_get = get or (lambda u: httpx.get(u, timeout=3.0))
    try:
        resp = do_get(base_url)
        return Reach(name, True, f"HTTP {resp.status_code}")
    except Exception as e:  # noqa: BLE001 - any failure means unreachable
        return Reach(name, False, type(e).__name__)


def main(argv: list[str]) -> int:
    from app.config import load_config

    config = load_config()
    rows = [probe(p.name, p.base_url) for p in config.providers]
    print(format_reachability(rows))
    print("\nSee docs/chaos-check.md for the full Wi-Fi-kill procedure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
