# 05_IMPLEMENTATION_PLAN: Build Sequence

The order of work, phase gates, and setup. Atomic tasks live in [06_TASK_QUEUE.md](06_TASK_QUEUE.md) and reference these phases; standards while building are in [04_ENGINEERING_RULES.md](04_ENGINEERING_RULES.md); the repository layout being built toward is 02_ARCHITECTURE §8.

Phase gates are hard: nothing from a later phase starts before the current phase's exit criteria are met. Content sessions (C1, C2, ...) are done with Claude and the source PDFs, not the codebase, and interleave with build phases.

## Phase 0: Environment + accounts (1 evening)

1. Install Homebrew if absent; `brew install python@3.12 ffmpeg`
2. Groq account + API key (console.groq.com); Nvidia Developer Program + key (build.nvidia.com)
3. Install Piper (`pip install piper-tts` or binary release); download one voice (en_US-lessac-medium)
4. `python -m venv .venv`; requirements.txt: fastapi, uvicorn, httpx, pydantic, pytest, python-dotenv
5. Record the free-tier limits you actually see in both consoles into `docs/decisions.md` with the date (docs elsewhere cite indicative numbers only; yours are the truth)
6. Smoke tests: one Groq chat completion, one Nvidia chat completion, one Groq Whisper transcription of a recorded sentence, one Piper WAV
7. Deferrable: `brew install ollama` + `ollama pull qwen2.5:3b-instruct-q4_K_M` for the offline profile

**Exit:** all smoke tests pass; verified limits recorded.

## Session C1: Seed content (1 session; may precede or run parallel to Phase 1)

Per 03_CONTENT_SPEC §5: benchmark reconciliation → `benchmarks.json`; 2 lessons from the Saraf notes (case interview basics, profitability tree); 3 guesstimates from the IIT G book; 2 cases from CIC IITB (one with a full coaching block, one flagged diagnostic). Settle PRD open question 6 (which 2 cases) here.

**Exit:** everything passes the validator and a human read-through.

## Phase 1: Core loop, typed, terminal (2-3 sessions)

Content schemas as pydantic models, content loader with skip-with-warning, provider router (Groq only), prompt template loading, case + lesson state machines, coach and interviewer personas, guided case flow, lesson flow with quiz, terminal chat.

**Exit:** MVP criteria for lesson + guided case (PRD §8) met in the terminal, 5 consecutive clean runs.

## Phase 2: Guesstimates + persistence + scoring (2-3 sessions)

Guesstimate flow (coached), SQLite persistence, transcript recording, chunked scoring with evidence quotes, model answer reveal, math checker for both content types, diagnostic session flow, Nvidia fallback + failover + 429 backoff, pre-commit validation hook.

**Exit:** coached guesstimate verifies arithmetic per step; planted math errors are caught; a deliberately bad run scores visibly lower than a good run; killing Groq access mid-test fails over to Nvidia.

## Phase 3: Web UI (2-3 sessions)

FastAPI serving the frontend with streaming (SSE or WebSocket: settle REVIEW_REPORT G-2 first), chat pane, exhibit viewer, timer, provider status indicator, lesson reader, guesstimate step view, session review screen.

**Exit:** a full lesson, case, and guesstimate each run comfortably in the browser without touching the terminal.

## Phase 4: Voice (2-3 sessions)

Push-to-talk capture (MediaRecorder), Groq Whisper STT client, transcript cleanup + number confirmation step, Piper output with sentence-level streaming, latency benchmarks.

**Exit:** V1 voice criteria (PRD §8): sub-3s median response gap on a full voice case.

## Session C2: Content expansion (1-2 sessions)

Remaining IIT G guesstimates; 3-4 more CIC cases; 2-3 more lessons.

## Phase 5: Ladder + dashboard + drills (2 sessions)

Recommendation engine, concept coverage map, score trends, weakness flags, mental math sprints, benchmark flashcards, standard and cold modes wired to graduation rules.

**Exit:** after 5 sessions the home screen recommends a defensible next step; new valid content dropped in a folder appears in the library, invalid content warns without crashing (PRD §8 V1 criteria).

## Phase 6: Depth (ongoing)

More content (C3, C4, ...), interviewer-led mode, timed guesstimates, hints with score cost, curveballs, PEI mode from Day One material, framework reference page, offline whisper.cpp profile if ever needed, polish.

## Effort estimate

10-15 build sessions plus 2-3 content sessions to a usable V1. Content is the long pole; the C-session structure is how it stays on track.

## Prerequisite skills (learnable in-flight)

- Python + venv + pip (required)
- HTTP errors, headers, retry logic (required; the failover logic is the one genuinely new skill)
- FastAPI + one streaming pattern (Phase 3)
- JS fetch + MediaRecorder (Phase 4)
- SQLite CRUD (Phase 2)
- Prompt iteration patience: three personas to tune (07_PROMPTS)
