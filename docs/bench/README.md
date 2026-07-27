# Latency benchmarks (T-054)

`scripts/bench_latency.py` measures the four legs of a voice turn per chat
provider and records the sub-3s **response-gap** gate (V1 voice criterion,
PRD §8 / 05 §Phase 4).

## Run

```sh
python scripts/bench_latency.py --audio clip.webm -n 5
```

Needs a real recorded clip (Groq Whisper transcribes it) and reachable providers.
Each turn appends one line to `history.jsonl` and the run prints per-provider
medians plus PASS/FAIL against the gate.

## Legs

| field              | meaning                                            |
|--------------------|----------------------------------------------------|
| `stt_ms`           | Groq Whisper transcription of the clip             |
| `first_token_ms`   | LLM time-to-first-token                            |
| `full_response_ms` | LLM full streamed response                         |
| `tts_start_ms`     | Piper synthesis of the first sentence             |

**Response gap** (what the gate checks) = `stt_ms + first_token_ms + tts_start_ms`
— end of speech to first audio out. Target: **median ≤ 3000 ms**.

## History format

`history.jsonl` is append-only, one JSON object per turn:

```json
{"ts": "2026-07-28T...", "provider": "groq", "stt_ms": 820.0, "first_token_ms": 410.0, "full_response_ms": 2100.0, "tts_start_ms": 260.0}
```

Commit updated runs here so the gate has history. `summarize()` in the script
turns these rows into the medians/p90/max and the gate verdict.
