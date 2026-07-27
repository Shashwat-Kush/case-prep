#!/usr/bin/env python3
"""Voice-turn latency benchmark (T-054, 05 §Phase 4).

Measures the four legs of a voice turn — STT, LLM first-token, LLM full-response,
and TTS-start — per chat provider over N iterations, appends every sample to
`docs/bench/history.jsonl`, and prints per-provider medians plus the sub-3s
response-gap verdict (the V1 voice gate, PRD §8).

The user-perceived gap is end-of-speech -> first audio out, i.e.
STT + LLM-first-token + TTS-start (full-response is reported but not part of the
gate). Run with a real recorded clip:

    python scripts/bench_latency.py --audio clip.webm -n 5

The aggregation math (`summarize`, `percentile`) is pure and unit-tested; the run
path touches the network and is exercised by hand.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GATE_S = 3.0  # median response-gap target (PRD §8)
LEGS = ("stt_ms", "first_token_ms", "full_response_ms", "tts_start_ms")
BENCH_DIR = Path(__file__).resolve().parent.parent / "docs" / "bench"


@dataclass(frozen=True)
class TurnSample:
    provider: str
    stt_ms: float
    first_token_ms: float
    full_response_ms: float
    tts_start_ms: float

    @property
    def gap_ms(self) -> float:
        return self.stt_ms + self.first_token_ms + self.tts_start_ms


# --- pure aggregation (unit-tested) -----------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile; stable for the small N a manual bench produces."""
    xs = sorted(values)
    if not xs:
        return 0.0
    k = max(0, math.ceil(q * len(xs)) - 1)
    return xs[k]


def _gap(s: dict) -> float:
    return s["stt_ms"] + s["first_token_ms"] + s["tts_start_ms"]


def summarize(samples: list[dict]) -> dict:
    """Aggregate per-turn samples into per-provider medians/p90/max per leg (plus
    the derived response gap) and the overall sub-3s gate verdict."""
    by_provider: dict[str, list[dict]] = {}
    for s in samples:
        by_provider.setdefault(s["provider"], []).append(s)

    providers = {}
    for prov, rows in by_provider.items():
        stats = {}
        for leg in (*LEGS, "gap_ms"):
            vals = [_gap(r) if leg == "gap_ms" else r[leg] for r in rows]
            stats[leg] = {
                "median": statistics.median(vals),
                "p90": percentile(vals, 0.9),
                "max": max(vals),
            }
        providers[prov] = {"n": len(rows), **stats}

    gaps = [_gap(s) for s in samples]
    median_gap = statistics.median(gaps) if gaps else 0.0
    return {
        "n": len(samples),
        "median_gap_ms": median_gap,
        "gate_s": GATE_S,
        "passes_gate": bool(gaps) and median_gap <= GATE_S * 1000,
        "providers": providers,
    }


def load_samples(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _row(s: TurnSample) -> dict:
    return {"provider": s.provider, **{leg: getattr(s, leg) for leg in LEGS}}


# --- run path (manual; network) ---------------------------------------------


def _time_ms(fn):
    start = time.monotonic()
    result = fn()
    return result, (time.monotonic() - start) * 1000


def run_turn(provider, chat_client, stt, tts, audio: bytes, prompt: str) -> TurnSample:
    """One measured turn against a single provider. Raises on hard failure so the
    caller can record and skip; degraded STT/TTS surface as inf on that leg."""
    from app.speech.tts import split_sentences

    tr, stt_ms = _time_ms(lambda: stt.transcribe(audio))
    stt_ms = stt_ms if (tr and tr.ok) else math.inf

    messages = [{"role": "user", "content": prompt}]
    stream = chat_client.stream(messages)
    it = iter(stream)
    t0 = time.monotonic()
    first = next(it)  # first content token
    first_token_ms = (time.monotonic() - t0) * 1000
    reply = first + "".join(it)
    full_response_ms = (time.monotonic() - t0) * 1000

    sentences = split_sentences(reply)
    if sentences:
        _, tts_start_ms = _time_ms(lambda: tts.synthesize(sentences[0]))
    else:
        tts_start_ms = math.inf
    return TurnSample(
        provider.name, stt_ms, first_token_ms, full_response_ms, tts_start_ms
    )


def _print_summary(summary: dict) -> None:
    print(
        f"\n{summary['n']} turns · median response gap "
        f"{summary['median_gap_ms']:.0f} ms · gate {summary['gate_s']}s · "
        f"{'PASS' if summary['passes_gate'] else 'FAIL'}"
    )
    for prov, st in summary["providers"].items():
        print(f"  {prov} (n={st['n']}):")
        for leg in (*LEGS, "gap_ms"):
            m = st[leg]
            print(
                f"    {leg:18} median {m['median']:8.0f}  p90 {m['p90']:8.0f}  "
                f"max {m['max']:8.0f} ms"
            )


def main(argv: list[str]) -> int:
    from app.config import load_config
    from app.providers.llm_client import ChatClient
    from app.providers.stt_client import SttClient
    from app.speech.tts import PiperTTS

    ap = argparse.ArgumentParser(description="Voice-turn latency benchmark (T-054)")
    ap.add_argument("--audio", required=True, help="path to a recorded voice clip")
    ap.add_argument("-n", type=int, default=5, help="iterations per provider")
    ap.add_argument("--prompt", default="Walk me through your structure.")
    args = ap.parse_args(argv[1:])

    config = load_config()
    audio = Path(args.audio).read_bytes()
    stt = SttClient(config.stt)
    tts = PiperTTS(config.voice)

    samples: list[TurnSample] = []
    for provider in config.providers:
        client = ChatClient(provider, timeout_s=config.retry.request_timeout_s)
        for i in range(args.n):
            try:
                samples.append(run_turn(provider, client, stt, tts, audio, args.prompt))
            except Exception as e:  # noqa: BLE001 - bench records and continues
                print(f"  {provider.name} turn {i + 1} failed: {type(e).__name__}: {e}")

    if not samples:
        print("no successful turns — check providers/network")
        return 1

    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).isoformat()
    with (BENCH_DIR / "history.jsonl").open("a") as f:
        for s in samples:
            f.write(json.dumps({"ts": ts, **_row(s)}) + "\n")

    _print_summary(summarize([_row(s) for s in samples]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
