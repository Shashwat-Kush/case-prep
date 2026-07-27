#!/usr/bin/env python3
"""Provider smoke test (T-003, Phase 0 exit).

Verifies each leg of a voice turn end to end — every configured chat provider
(Groq, Nvidia, Ollama), Groq Whisper (STT), and Piper (TTS) — printing pass/fail
with latency and, on failure, the provider and error class. STT reuses the WAV
Piper just produced (a real TTS->STT loop) unless you pass a clip with --audio.
It also prints the manual checklist for recording verified rate limits in
docs/decisions.md (04 §3). Run after Phase 0 steps 2-3:

    python scripts/smoke.py [--audio clip.webm]

Exit is nonzero if any check failed (skips do not count). Network-facing; the
output formatting is the only unit-tested part.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHECKLIST = """\
Manual step — record verified limits in docs/decisions.md (04 §3):
  [ ] Groq chat: requests/min, tokens/min, daily cap
  [ ] Nvidia chat: requests/min, monthly credit cap
  [ ] Groq Whisper: audio seconds/min or requests/min
  [ ] Piper: model + voice confirmed local, no network"""


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool | None  # True pass, False fail, None skipped
    latency_ms: float | None
    error: str | None  # "ErrorClass: message" on failure


# --- pure output (unit-tested) ----------------------------------------------


def _line(r: CheckResult) -> str:
    status = "PASS" if r.ok else ("SKIP" if r.ok is None else "FAIL")
    lat = f"{r.latency_ms:.0f} ms" if r.latency_ms is not None else "—"
    tail = f"  {r.error}" if r.error else ""
    return f"{status}  {r.name:20} {lat:>9}{tail}"


def format_results(results: list[CheckResult]) -> str:
    return "\n".join(_line(r) for r in results)


def exit_code(results: list[CheckResult]) -> int:
    return 1 if any(r.ok is False for r in results) else 0


# --- checks (network) -------------------------------------------------------


def _check_chat(provider) -> CheckResult:
    from app.providers.llm_client import ChatClient

    name = f"{provider.name} chat"
    if provider.api_key_env and not provider.api_key():
        return CheckResult(name, False, None, f"missing {provider.api_key_env}")
    start = time.monotonic()
    try:
        text = "".join(
            ChatClient(provider).stream([{"role": "user", "content": "ping"}])
        )
    except Exception as e:  # noqa: BLE001 - smoke reports every failure class
        return CheckResult(name, False, _ms(start), f"{type(e).__name__}: {e}")
    return CheckResult(name, bool(text), _ms(start), None if text else "empty response")


def _check_tts(voice: str) -> tuple[CheckResult, bytes | None]:
    from app.speech.tts import PiperTTS

    name = "piper (tts)"
    start = time.monotonic()
    try:
        wav = PiperTTS(voice).synthesize("Testing one two three.")
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, False, _ms(start), f"{type(e).__name__}: {e}"), None
    if not wav:
        return CheckResult(name, False, _ms(start), "no audio (piper missing?)"), None
    return CheckResult(name, True, _ms(start), None), wav


def _check_stt(stt_cfg, audio: bytes | None) -> CheckResult:
    from app.providers.stt_client import SttClient

    name = "groq whisper (stt)"
    if not audio:
        return CheckResult(name, None, None, "no audio (pass --audio or install piper)")
    r = SttClient(stt_cfg).transcribe(audio)
    return CheckResult(name, r.ok, r.latency_ms, None if r.ok else r.error)


def _ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


def main(argv: list[str]) -> int:
    from app.config import load_config

    ap = argparse.ArgumentParser(description="Provider smoke test (T-003)")
    ap.add_argument("--audio", help="clip for the STT check (else Piper's output)")
    args = ap.parse_args(argv[1:])

    config = load_config()
    results = [_check_chat(p) for p in config.providers]
    tts_result, wav = _check_tts(config.voice)
    results.append(tts_result)
    audio = Path(args.audio).read_bytes() if args.audio else wav
    results.append(_check_stt(config.stt, audio))

    print(format_results(results))
    print("\n" + CHECKLIST)
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
