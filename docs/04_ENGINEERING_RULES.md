# 04_ENGINEERING_RULES: Engineering Handbook

How code in this repository is written, tested, and operated. Binding for humans and AI coding agents alike. System shape is in [02_ARCHITECTURE.md](02_ARCHITECTURE.md); work items in [06_TASK_QUEUE.md](06_TASK_QUEUE.md); decision rationale in [08_ARCHITECTURE_DECISIONS.md](08_ARCHITECTURE_DECISIONS.md).

## 1. Code quality

- Python 3.12, type hints on all public functions and pydantic models everywhere data crosses a boundary (content files, API payloads, DB rows).
- Small modules with one responsibility, matching the component table in 02_ARCHITECTURE §2. If a file needs a section comment to navigate, split it.
- No dead code, no commented-out code, no TODOs without a task ID from 06_TASK_QUEUE.
- Functions that touch external systems (LLM, STT, disk, DB) stay thin; logic lives in pure functions that tests can call without mocks.
- Formatting and linting: `ruff format` + `ruff check` with default rules; both clean before any commit.

## 2. Architecture principles (operationalized ADRs)

- Content is read-only input to the app; nothing in `app/` writes to content folders (ADR-8).
- No component other than the provider router imports provider SDKs or knows base URLs (ADR-5).
- No component other than the math checker parses or verifies user arithmetic (ADR-3).
- State transitions happen only in the session manager; prompt text never encodes state logic (ADR-2).
- The interviewer persona's context must never contain `model_answer` or solution text; enforce by construction in context assembly, not by prompt instruction alone (07_PROMPTS §4).
- Single process; do not introduce Docker, task queues, or services without a new ADR.

## 3. Naming conventions

- Python: `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE` constants.
- Content ids: `kebab-case`, prefixed by type: `case-`, `guess-`, `lesson-` (e.g. `case-cement-profitability`). Benchmark keys: `snake_case` (e.g. `india_population`).
- Modes are exactly: `guided | standard | cold` (cases), `coached | timed` (guesstimates). Personas are exactly: `interviewer | coach | tutor`. Do not introduce synonyms in code, UI, or prompts.
- DB tables plural (`sessions`, `turns`); columns `snake_case`.
- Task IDs `T-nnn` per 06_TASK_QUEUE; ADRs `ADR-n`.

## 4. Dependency injection

- Constructor injection, no DI framework. The FastAPI app composes the object graph at startup: content loader, provider router, math checker, scoring orchestrator, session manager, DB store.
- Every external dependency (LLM client, STT client, TTS worker, clock, DB connection) is injected as an interface-like protocol so tests substitute fakes. `time.time()` and `datetime.now()` are never called directly inside engine logic; inject a clock.

## 5. Error handling

Error taxonomy for provider calls:

| Class | Examples | Handling |
|---|---|---|
| Retryable | 429 with retry-after, transient network errors, 5xx | Honor retry-after exactly when present; else exponential backoff with jitter; max 2 retries per provider |
| Failover | retries exhausted, daily-cap error, connection refused | Move to next provider in configured order; record the switch |
| Fatal-for-turn | invalid request, auth failure (401/403) | Surface a clear user-facing message naming the provider; do not silently retry auth failures |
| Degrade | STT failure, TTS failure | STT → prompt user to type; TTS → show text only. Never fail a session for a speech error |

General rules: no bare `except:`; exceptions carry context (provider, endpoint, session id); user-facing errors say what happened and what still works. Content loading errors are warnings, never crashes (03_CONTENT_SPEC §3). Auth failure on a provider mid-chain triggers failover after surfacing the message once per session.

## 6. Logging and observability

- Structured logging (JSON lines) to a local file: every turn logs phase, persona, provider, model, latencies (STT, first token, full response, TTS start), token counts, and remaining x-ratelimit-* headers when present.
- Log levels: DEBUG (context assembly detail), INFO (turns, transitions, failovers), WARNING (skipped content, degradations), ERROR (fatal-for-turn).
- Never log API keys. Transcript text may be logged locally (it is already stored in SQLite; this is a single-user local tool).
- `scripts/check_limits.py` prints current per-provider headroom. A `/debug` endpoint dumps live session state.
- All transcripts are kept; they are product data and debugging data.

## 7. Configuration management

- `config.yaml` holds all behavior: provider order, per-provider model names, voice, ports, offline flag, score-visibility flag, ladder rules. Behavior changes must be possible without code edits.
- Config is validated by a pydantic model at startup; fail fast with a readable message on invalid config.
- No magic numbers in code for anything a user might tune (timeouts, retry counts, time budgets): they belong in config with defaults.

## 8. Security

- Keys live in `.env` (gitignored), documented by name in `.env.example`, loaded via python-dotenv. Never in code, logs, or the frontend: all provider calls go through the backend, so keys never reach the browser.
- The backend binds to localhost only. No auth is implemented because no non-local access exists; adding remote access requires a new ADR.
- Content files are trusted repo data but still validated before use; the app must survive malformed input (03_CONTENT_SPEC §3).
- Rotate any leaked key at the provider console; keys are free-tier but treat hygiene as habit.

## 9. Performance

- Budgets are contracts: per-voice-turn targets and RAM budget in 02_ARCHITECTURE §7. A change that regresses the median response gap or exceeds token/min caps is a bug.
- Per-call LLM context stays phase-scoped and trimmed (ADR-2); the scoring path stays chunked (ADR-6). Any new LLM call type must state its worst-case token cost in its PR/task notes.
- Latency benchmark script runs per phase gate and logs per-provider numbers; keep history in the repo.

## 10. Documentation standards

- `docs/decisions.md` (repo) records: verified provider limits at Phase 0 (with date), any deviation from this handbook, and new ADRs proposed during implementation.
- Public functions get docstrings stating contract, not narration. Comments explain why, never what.
- README stays runnable: a fresh machine following it must reach the smoke tests. Update it in the same commit as any setup-affecting change.
- The content authoring guide tracks the pydantic models (03_CONTENT_SPEC §7).

## 11. Testing philosophy

- Test pyramid: many unit tests on pure logic (math checker both paths, content loader valid/invalid/missing-benchmark-ref, state machine transitions per flow, ladder rules); few integration tests (provider router against mocked HTTP; DB round-trips); a thin end-to-end smoke (scripted typed case in the terminal).
- Provider router tests are mandatory before any cloud code merges: mocked 429 with retry-after asserts exact backoff; mocked network failure asserts failover order; offline flag asserts cloud is never called.
- Prompt regression suite (`scripts/run_regression.py`): 10-15 canned inputs per persona, checked for leaked solutions, invented numbers, broken character, and (coach) answers-before-attempt. Run before and after any prompt edit; mind the daily request budget when running repeatedly. Details in 07_PROMPTS §6.
- Chaos check once per phase: run a session, kill Wi-Fi mid-turn, assert graceful degradation to the offline profile rather than a crash.
- Deterministic tests only: fake clock, fixed seeds, no real network in unit tests.
- Every task in 06_TASK_QUEUE ships with its listed tests; a task is not done with failing or missing tests.

## 12. Version control and ops

- Git from day one; private GitHub repo is the code + content backup. Small commits; imperative messages referencing task IDs ("T-023: case checkpoint parser"). Tag each phase gate (`phase-1`, `phase-2`, ...).
- Pre-commit hook runs the content validator on content folders and ruff on code.
- `app.db` backup: nightly launchd job copying to iCloud Drive or an external folder; it holds all progress history. Model files are re-downloadable, never backed up.
- Prompts are versioned files; a bad prompt edit is one revert away.

## 13. AI coding agent guidelines

For Claude Code, Cursor, Windsurf, ChatGPT, and similar agents working in this repo:

1. Start from [06_TASK_QUEUE.md](06_TASK_QUEUE.md). Work exactly one task; do not fold in adjacent improvements.
2. Before coding, read the task's referenced docs sections. If the task conflicts with an ADR, stop and flag; do not resolve silently.
3. Touch only the files the task lists (plus their tests). Never modify content folders, `.env`, or `docs/` except where the task says so.
4. No new dependencies without adding them to the task notes and `requirements.txt` in the same change, with one line of justification.
5. Run the task's tests plus the full unit suite before declaring done. Paste results, don't summarize them.
6. Do not rename public modules, ids, modes, or personas (§3); naming changes require a review-report entry or ADR.
7. Prompt files are code: edits to `app/llm/` templates require a regression suite run (§11).
8. If a spec is ambiguous, check REVIEW_REPORT.md first; if unlisted, ask, and record the resolution in `docs/decisions.md`.
9. Keep diffs reviewable: prefer several small commits within a task over one large one.
