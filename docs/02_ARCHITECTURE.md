# 02_ARCHITECTURE: System Design

The shape of the system and its runtime behavior. Feature intent lives in [01_PRD.md](01_PRD.md); the reasoning behind each structural choice lives in [08_ARCHITECTURE_DECISIONS.md](08_ARCHITECTURE_DECISIONS.md) (referenced as ADR-n); content schemas live in [03_CONTENT_SPEC.md](03_CONTENT_SPEC.md).

## 1. System overview

```
Browser (frontend: plain HTML/JS + SSE — G-2 settled, T-040)
  |  mic audio (push-to-talk), text, UI events
  v
FastAPI backend (Python, single process)     <- owns all state (ADR-2)
  |-- Content loader (scans folders, validates, skip-with-warning; ADR-8)
  |-- Session manager
  |     state machines: case flow, guesstimate flow, lesson flow
  |     timers, ladder position
  |-- Math checker (deterministic; case checkpoints + guesstimate segments; ADR-3)
  |-- Scoring orchestrator (chunked; ADR-6)
  |-- Ladder/recommendation engine (simple rules over progress data)
  |-- SQLite store (user data only: sessions, turns, scorecards, coverage)
  |-- Provider router (ADR-5)
  |     |-- LLM client (OpenAI-compatible): Groq | Nvidia | Ollama
  |     '-- STT client: Groq Whisper | (V2) whisper.cpp
  '-- TTS worker -> Piper (local subprocess, streams WAV)
```

Single process. No Docker, no queues, no microservices: one user on one laptop.

## 2. Component responsibilities

| Component | Owns | Must not |
|---|---|---|
| Content loader | Discovering, parsing, validating content files at startup and on refresh; exposing the valid set; surfacing warnings for invalid files | Crash on bad input; cache stale content after a refresh |
| Session manager | Current phase, unlocked exhibits, elapsed time, mode, ladder position; assembling per-call LLM context | Let the LLM decide phase transitions |
| Math checker | Parsing numbers from user turns; comparing against case checkpoints or guesstimate segment values with tolerances | Ask the LLM to verify arithmetic |
| Scoring orchestrator | Chunked rubric evaluation over the full transcript; assembling scorecards with evidence quotes | Send the full transcript in one call (ADR-6) |
| Provider router | Provider order, retries, backoff, failover, offline profile; recording provider + latency per call | Leak provider specifics into engine code |
| SQLite store | Sessions, turns (role, text, timestamp, phase, provider, latency), scorecards, concept coverage, ladder state | Store content; content stays on disk as files (ADR-8) |
| TTS worker | Sentence-level Piper synthesis, streaming to browser | Block the response pipeline; TTS failures degrade to text |

## 3. Provider strategy

| Layer | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| LLM | Groq (llama-3.3-70b-versatile) | Nvidia build.nvidia.com (Llama 3.3 70B or DeepSeek) | Ollama local (qwen2.5:3b) |
| STT | Groq hosted Whisper | (V2) whisper.cpp local | Typed input |
| TTS | Piper local | macOS `say` | On-screen text only |

All three LLM providers speak the OpenAI-compatible chat API, so one client with a swappable base URL, model name, and key covers them. Provider order, per-provider model names, and the offline flag live in `config.yaml`; keys live in `.env` (see 04_ENGINEERING_RULES §7-8).

**Free-tier constraints to design around** (indicative; verify at Phase 0 and record actuals in `docs/decisions.md`, they change):

- Groq: ~30 requests/min, ~6K-12K tokens/min depending on model, ~1,000 requests/day on large models. Organization-level; extra keys don't raise them. 429 responses carry a retry-after header and x-ratelimit-* headers.
- Groq Whisper: ~2,000 audio requests/day, capped audio seconds per hour. Far beyond one user's practice volume.
- Nvidia: ~40 requests/min, rate-limited trial for Developer Program members, dev/test/research use only. A single-owner personal tool satisfies this; multi-user serving would not (hence the PRD non-goal).

A practice session is roughly 40-80 LLM calls per hour, so per-minute request caps are a non-issue at conversational pace. The binding constraint is tokens per minute, managed by per-call context trimming (ADR-2) and chunked scoring (ADR-6).

**Failover triggers:** HTTP 429 persisting after retry-after-honoring backoff, network errors, or a daily-cap error. The offline flag skips cloud providers entirely. Error taxonomy and retry rules are specified in 04_ENGINEERING_RULES §5.

## 4. Runtime flows

**Voice turn (V1):** browser records on push-to-talk → audio to backend → STT client (Groq Whisper) → transcript cleanup pass; any stated number surfaces a UI confirmation → session manager appends turn, assembles phase-scoped context → provider router streams LLM reply → TTS worker starts Piper on the first complete sentence → audio streams to browser. Typed turns skip STT/TTS.

**End of case:** scoring orchestrator runs 2-3 sequential chunked calls (one per rubric group) over the stored transcript, honoring retry-after, targeting whichever provider has headroom (ADR-6) → scorecard with evidence quotes persisted → model answer revealed from the case file.

**Content refresh:** loader rescans folders, re-validates, atomically swaps the in-memory library, reports skipped files with reasons.

**Offline degradation:** on failover exhaustion or offline flag, LLM routes to Ollama, voice input degrades to typed, LLM-free drills remain fully functional. Mid-session network loss must degrade, not crash (chaos check, 04_ENGINEERING_RULES §11).

## 5. State machines

Three flows, all backend-owned (ADR-2):

- **Case flow:** opening → clarifying → structuring → analysis → math → synthesis. Guided mode inserts a coach step (explain → user attempt → model approach reveal) at each phase boundary. Interviewer-led mode (V1) reorders control but reuses phases.
- **Guesstimate flow:** clarify → approach choice (top-down/bottom-up) → segmentation → estimation (per segment, arithmetic checked) → sanity check. Coached mode pauses at each step; timed mode runs a 10-15 min clock.
- **Lesson flow:** section walk-through with free-form Q&A → quiz → coverage recorded.

Each LLM call receives only the current step's instructions plus recent transcript. The interviewer persona's context never contains model answers or solution text (07_PROMPTS §4).

## 6. Data stores

- `cases/`, `guesstimates/`, `lessons/`, `benchmarks.json`: version-controlled content; the folder is the manifest, no index file (ADR-8). Schemas in 03_CONTENT_SPEC.
- `app.db` (SQLite): user data only. Tables: sessions, turns, scorecards, concept_coverage, ladder_state. Linked to content by content `id`; content edits/deletions never touch history.
- `config.yaml`: provider order, per-provider model names, voice, ports, offline flag, score-visibility flag, ladder rules.
- `.env` (gitignored): GROQ_API_KEY, NVIDIA_API_KEY.

## 7. Resource and latency budgets

RAM, default cloud profile (8GB machine):

| Component | RAM |
|---|---|
| macOS + background | ~3.0 GB |
| FastAPI + Python | ~0.2 GB |
| Piper | ~0.1 GB |
| Browser tab | ~0.4 GB |
| **Headroom** | **~4.3 GB** |

Ollama (qwen2.5:3b Q4, ~2.3 GB) loads only in the offline profile. The scarce resource in the default profile is API tokens per minute, not RAM.

Latency targets per voice turn: STT under 1s for a 20s clip; LLM first token under 0.5s; Piper start under 0.3s; **median response gap under 3s** (V1 success criterion, PRD §8). Latency benchmarks are logged per provider (04_ENGINEERING_RULES §6).

## 8. Repository layout

```
caseprep/
  README.md            setup + run instructions
  config.yaml
  .env.example         key names, no values
  requirements.txt
  cases/  guesstimates/  lessons/  benchmarks.json
  app/
    main.py
    engine/            state machines, content loader, math checker,
                       scoring, ladder rules
    providers/         router.py, llm_client.py, stt_client.py
    llm/               prompt templates as files (07_PROMPTS)
    speech/            tts.py
    db/
  web/
  scripts/
    validate_case.py   validates all four content types (03_CONTENT_SPEC §4)
    check_limits.py    prints remaining rate-limit headroom per provider
    run_regression.py  prompt regression suite (07_PROMPTS §6)
  tests/
  docs/                this documentation system + decisions.md
```

No conversion scripts: content conversion happens outside the codebase (ADR-8).
