# 06_TASK_QUEUE: Atomic Tasks

The work items. One task per coding session or agent run; obey [04_ENGINEERING_RULES.md](04_ENGINEERING_RULES.md) §13 while executing. Tasks map to phases in [05_IMPLEMENTATION_PLAN.md](05_IMPLEMENTATION_PLAN.md); "Docs" lists the sections to read before starting. File paths are relative to the repo root (layout: 02_ARCHITECTURE §8). Every task implicitly includes: run full unit suite, ruff clean, commit referencing the task ID.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done. Update statuses in place.

---

## Phase 0

**T-001 · Repo scaffold** `[ ]`
Goal: initialize the repository skeleton and tooling.
Files: full tree per 02_ARCHITECTURE §8 (empty modules), `.gitignore` (.env, .venv, app.db, __pycache__), `requirements.txt`, `ruff` config, `README.md` stub, `.env.example`.
Depends: none.
Accept: fresh clone + venv + `pip install -r requirements.txt` succeeds; `ruff check` clean; git initialized with first commit.
Tests: none (scaffold); CI-style check is the accept criteria themselves.

**T-002 · Config + secrets loading** `[ ]`
Goal: `config.yaml` and `.env` loading with validation.
Files: `app/config.py`, `config.yaml` (defaults: provider order, models, ports, offline=false, score_visibility, ladder rules placeholder), `.env.example`.
Depends: T-001.
Accept: invalid config fails fast with a readable message; keys never appear in logs; all tunables from 04_ENGINEERING_RULES §7 present with defaults.
Tests: valid config parses; missing required key fails; malformed yaml fails with filename in message.

**T-003 · Provider smoke script** `[ ]`
Goal: verify Groq chat, Nvidia chat, Groq Whisper, and Piper end to end (Phase 0 exit).
Files: `scripts/smoke.py`.
Depends: T-002; Phase 0 steps 2-3 done manually.
Accept: script prints pass/fail per provider with latency; failures name the provider and error class; verified limits recorded in `docs/decisions.md` (manual step, checklist printed by script).
Tests: none (network script); unit-test the output formatting only.

---

## Phase 1

**T-010 · Content schemas (pydantic)** `[ ]`
Goal: executable models for all four content types.
Files: `app/engine/content_models.py`.
Depends: T-001. Docs: 03_CONTENT_SPEC §2.
Accept: models cover every field incl. optional ones; ids validated against naming rules (04 §3); mode/persona enums centralized here.
Tests: each schema accepts a minimal valid fixture and rejects fixtures missing required fields; id pattern enforcement.

**T-011 · Content validator core** `[ ]`
Goal: shared validation logic (schema + math recomputation + reference checks).
Files: `app/engine/validation.py`, test fixtures under `tests/fixtures/content/`.
Depends: T-010. Docs: 03_CONTENT_SPEC §4.
Accept: all six checks implemented; math checkpoints and guesstimate trees actually recomputed; violations return structured errors (file, check, detail), not exceptions.
Tests: one fixture per failure class (bad schema, wrong checkpoint, broken tree, missing benchmark ref, dangling exhibit/lesson ref, duplicate id) + one fully valid set.

**T-012 · Validator CLI + pre-commit** `[x]`
Goal: `scripts/validate_case.py` wrapping T-011 for all content folders; git pre-commit hook (validator + ruff).
Files: `scripts/validate_case.py`, `.githooks/pre-commit`, hook install note in README.
Depends: T-011.
Accept: CLI exits nonzero listing every violation; hook blocks commits with invalid content; runtime under 2s on the seed set.
Tests: CLI against valid and invalid fixture dirs.

**T-013 · Content loader** `[x]`
Goal: scan folders, validate, build in-memory library, skip-with-warning, atomic refresh.
Files: `app/engine/content_loader.py`.
Depends: T-011. Docs: 03_CONTENT_SPEC §3.
Accept: invalid file → warning with filename + failed check, app continues; refresh swaps atomically; library exposes lookup by id and by type.
Tests: mixed valid/invalid dir loads only valid; warning list correct; refresh picks up an added file; removed file disappears without touching (future) session data.

**T-014 · LLM client + provider router (Groq only)** `[x]`
Goal: OpenAI-compatible chat client with streaming; router shell with single provider.
Files: `app/providers/llm_client.py`, `app/providers/router.py`.
Depends: T-002. Docs: 02_ARCHITECTURE §3; 04 §5.
Accept: streaming tokens surface as an iterator; per-call record (provider, model, latencies, token counts, ratelimit headers) returned alongside; no provider specifics outside `app/providers/`.
Tests: against a mocked HTTP server: happy path, streamed chunks reassemble, headers captured.

**T-015 · Prompt template loader** `[x]`
Goal: file-based prompt templates with variable substitution; context assembly helpers.
Files: `app/llm/templates.py`, `app/llm/templates/*.md` (stubs for interviewer, coach, tutor).
Depends: T-001. Docs: 07_PROMPTS §3-4.
Accept: templates load from files; assembly function enforces the solution-exclusion rule by construction (interviewer context builder has no code path to model_answer).
Tests: substitution correctness; assembling interviewer context from a case fixture never contains model_answer text (assert on string absence).

**T-016 · Case state machine** `[x]`
Goal: phases, transitions, exhibit unlocking, per-phase context scoping.
Files: `app/engine/case_flow.py`.
Depends: T-010, T-015. Docs: 02_ARCHITECTURE §5.
Accept: transitions only via explicit engine calls; exhibits unlock per unlock_condition; per-call context contains only current-phase instructions + recent transcript window (size from config).
Tests: full transition table; exhibit gating; context scoping (token-count proxy: context excludes other phases' instructions).

**T-017 · Lesson flow + quiz** `[x]`
Goal: section walk-through with Q&A, quiz administration, coverage result.
Files: `app/engine/lesson_flow.py`.
Depends: T-010, T-015.
Accept: quiz graded deterministically where options exist, via rubric prompt where free-form; coverage result object emitted at completion.
Tests: quiz grading on fixture lesson; flow order; completion emits concepts_taught.

**T-018 · Guided mode (coach integration)** `[x]`
Goal: coach step (explain → user attempt → model approach reveal) at each case phase boundary.
Files: `app/engine/case_flow.py` (extend), `app/llm/templates/coach.md`.
Depends: T-016. Docs: 01_PRD Module A; 07_PROMPTS §2 (coach).
Accept: coaching block content used verbatim as ground truth; reveal happens only after a user attempt; standard mode unaffected.
Tests: guided sequence per phase; a case without a coaching block refuses guided mode with a clear message.

**T-019 · Terminal chat REPL** `[x]`
Goal: run lesson and guided/standard case flows end to end, typed, streaming.
Files: `app/cli.py`.
Depends: T-013, T-014, T-016, T-017, T-018.
Accept: Phase 1 exit criteria (05 §Phase 1) achievable; basic end-of-case feedback (single-call placeholder until T-025) shown.
Tests: scripted transcript drives a full guided case against a fake LLM client; assertions on flow order and no-crash.

---

## Phase 2

**T-020 · SQLite store** `[x]`
Goal: schema + persistence layer for sessions, turns, scorecards, concept_coverage, ladder_state.
Files: `app/db/store.py`, `app/db/schema.sql`.
Depends: T-001. Docs: 02_ARCHITECTURE §6.
Accept: content linked by id only; deleting a content file never orphans-crashes reads; turn rows carry role, text, timestamp, phase, provider, latency.
Tests: round-trips per table; session with missing content id still readable.

**T-021 · Transcript recording** `[x]`
Goal: every turn persisted through the session manager.
Files: `app/engine/session_manager.py` (extend), wiring in flows.
Depends: T-020, T-019.
Accept: a completed terminal case yields a complete ordered transcript in DB incl. provider + latency per assistant turn.
Tests: scripted case → DB rows match script.

**T-022 · Guesstimate flow (coached)** `[x]`
Goal: clarify → approach → segmentation → estimation → sanity-check state machine with coach persona.
Files: `app/engine/guess_flow.py`.
Depends: T-010, T-015, T-020. Docs: 02_ARCHITECTURE §5; 01_PRD Module J.
Accept: each step pauses in coached mode; segment estimates captured as structured numbers for T-024.
Tests: transition table; step data capture.

**T-023 · Math checker: case checkpoints** `[x]`
Goal: parse numbers from user turns; match against checkpoint inputs/expected within tolerance; detect common_errors patterns.
Files: `app/engine/math_checker.py`.
Depends: T-010. Docs: ADR-3; REVIEW_REPORT G-4 (number-parsing spec) must be settled first.
Accept: parses integers, decimals, Indian and Western groupings, %/lakh/crore/million/billion suffixes per the settled spec; tolerance respected; common_errors matched when close to a known-wrong value.
Tests: parsing matrix; correct/incorrect/tolerance-edge checkpoints; common-error identification.

**T-024 · Math checker: guesstimate segments** `[ ]`
Goal: verify each segment estimate against tree values and the final answer against answer_range.
Files: `app/engine/math_checker.py` (extend).
Depends: T-023, T-022.
Accept: per-step verification feeds coached-mode feedback; final range check recorded for scoring.
Tests: segment-by-segment fixture run incl. one planted wrong step.

**T-025 · Chunked scoring orchestrator** `[ ]`
Goal: 2-3 sequential rubric-group calls over the stored transcript; evidence quotes; provider-headroom aware.
Files: `app/engine/scoring.py`.
Depends: T-020, T-014. Docs: ADR-6; 01_PRD Module C.
Accept: no single call exceeds the configured token budget; scorecard has 1-5 per dimension + ≥3 verbatim user quotes; retry-after honored between chunks.
Tests: chunking against a long fixture transcript with a fake client (assert per-call token ceiling); scorecard assembly.

**T-026 · Model answer reveal + feedback assembly** `[ ]`
Goal: post-case reveal from the case file; "what to study next" hook (rule stub until T-061).
Files: `app/engine/scoring.py` (extend), CLI wiring.
Depends: T-025.
Accept: reveal text is file content verbatim; feedback references rubric anchors.
Tests: reveal equals file content; feedback includes anchor phrases.

**T-027 · Diagnostic session flow** `[ ]`
Goal: diagnostic-flagged case + 2 guesstimates as one session; scores recorded, hidden per config.
Files: `app/engine/session_manager.py` (extend).
Depends: T-021, T-022, T-025.
Accept: score-visibility flag suppresses display but not storage; ladder_state seeded.
Tests: hidden-score path stores full scorecard; visibility flag flips display.

**T-028 · Failover: Nvidia + backoff** `[ ]`
Goal: full router behavior: retry-after-honoring backoff, error taxonomy, provider order, offline flag.
Files: `app/providers/router.py` (extend).
Depends: T-014. Docs: 04_ENGINEERING_RULES §5.
Accept: taxonomy table implemented exactly; failover recorded in logs and turn rows; offline flag never touches network.
Tests (mandatory before merge, 04 §11): mocked 429+retry-after → exact wait; retries-exhausted → next provider; auth failure → surface once then failover; offline flag → zero HTTP calls.

**T-029 · Ollama offline profile** `[ ]`
Goal: local provider as last-resort/offline target.
Files: `app/providers/llm_client.py` (base-url reuse), config profile.
Depends: T-028; Phase 0 step 7.
Accept: offline profile runs a typed case end to end with Ollama; drills (later) unaffected.
Tests: router with offline flag selects Ollama; integration smoke documented as manual.

---

## Phase 3

**T-040 · FastAPI app + streaming transport** `[ ]`
Goal: serve frontend; stream turns via the transport chosen in G-2 (SSE or WebSocket).
Files: `app/main.py`, `web/` scaffold.
Depends: T-019 equivalents via API; G-2 settled.
Accept: localhost-only bind; a typed case runs over HTTP with streamed tokens.
Tests: endpoint contract tests with fake engine; stream reassembly.

**T-041 · Chat pane + session controls** `[ ]`
Goal: core conversation UI incl. mode selection and library list from the loader.
Files: `web/`.
Depends: T-040.
Accept: lesson, guided case, coached guesstimate each completable in browser.
Tests: minimal JS unit tests or scripted API-level checks; manual checklist in PR notes.

**T-042 · Exhibit viewer** `[ ]`
Goal: render exhibit tables/data on unlock.
Files: `web/`, exhibit payload endpoint.
Depends: T-041.
Accept: exhibits appear only when unlocked; data renders as tables.
Tests: unlock gating at API level.

**T-043 · Timer + phase pacing UI** `[ ]`
Goal: visible timer with per-phase budgets; overrun flag into feedback.
Files: `web/`, `app/engine/case_flow.py` (overrun capture).
Depends: T-041.
Accept: overruns recorded on the session and mentioned in feedback.
Tests: fake-clock overrun capture.

**T-044 · Provider status indicator** `[ ]`
Goal: show live provider + remaining headroom from captured ratelimit headers.
Files: `web/`, status endpoint.
Depends: T-028, T-040.
Accept: failover visibly updates the indicator.
Tests: status endpoint reflects router state.

**T-045 · Lesson reader + guesstimate step view** `[ ]`
Goal: dedicated UIs for lesson sections/quiz and guesstimate steps with per-step math feedback.
Files: `web/`.
Depends: T-041, T-022, T-024.
Accept: coached guesstimate shows per-step verification inline.
Tests: API-level step feedback contract.

**T-046 · Session review screen** `[ ]`
Goal: transcript with inline feedback annotations + scorecard.
Files: `web/`, review endpoint.
Depends: T-025, T-040.
Accept: quotes in the scorecard deep-link to their transcript turns.
Tests: annotation alignment on fixture session.

---

## Phase 4

**T-050 · Push-to-talk capture** `[ ]`
Goal: MediaRecorder capture, upload as audio file.
Files: `web/`.
Depends: T-041.
Accept: hold-to-record UX; audio reaches backend; typed input remains available.
Tests: manual checklist + endpoint accepts audio fixture.

**T-051 · STT client (Groq Whisper)** `[ ]`
Goal: transcription via provider router's STT arm; degrade-to-typed on failure.
Files: `app/providers/stt_client.py`, router wiring.
Depends: T-028, T-050.
Accept: failure follows Degrade row (04 §5); latency logged.
Tests: mocked endpoint happy/failure paths.

**T-052 · Transcript cleanup + number confirmation** `[ ]`
Goal: number-aware cleanup pass; UI confirm for any stated number before it reaches the math checker.
Files: `app/engine/stt_postprocess.py`, `web/` confirm UI.
Depends: T-051, T-023.
Accept: unconfirmed numbers never enter checkpoint evaluation; corrections editable inline.
Tests: cleanup cases (fifteen/fifty class errors, lakh/crore, currency); gating test.

**T-053 · Piper TTS + sentence streaming** `[ ]`
Goal: synthesize on first complete sentence; stream WAV; text-only degrade.
Files: `app/speech/tts.py`, `web/` audio playback.
Depends: T-040.
Accept: TTS start under 0.3s target measured; failure shows text only.
Tests: sentence-splitting; degrade path.

**T-054 · Latency benchmark script** `[ ]`
Goal: per-turn STT / first-token / full-response / TTS-start timings per provider, logged with history.
Files: `scripts/bench_latency.py`.
Depends: T-051, T-053.
Accept: produces the numbers for the sub-3s median gate (05 §Phase 4); results committed under `docs/bench/`.
Tests: timing math on fixture logs.

---

## Phase 5

**T-060 · Concept coverage map** `[ ]`
Goal: per-topic record of lessons done and case types attempted per mode.
Files: `app/engine/progress.py`, DB usage.
Depends: T-020, T-017.
Accept: coverage queryable per concept; feeds T-061.
Tests: coverage after scripted sessions.

**T-061 · Ladder rules + recommendations** `[ ]`
Goal: next-step recommendation from coverage + scores; graduation rule (standard 3+/5 average unlocks cold); config-driven.
Files: `app/engine/ladder.py`, config keys.
Depends: T-060, T-025.
Accept: recommendations are explainable strings citing the rule that fired; library never locked.
Tests: rule table across coverage/score fixtures incl. graduation edge.

**T-062 · Dashboard** `[ ]`
Goal: ladder view home screen, score trends per dimension, weakness flags.
Files: `web/`, aggregate endpoints.
Depends: T-061, T-046.
Accept: Phase 5 exit criterion (defensible next step after 5 sessions) demonstrable.
Tests: aggregation endpoints on fixture history.

**T-063 · Mental math sprints** `[ ]`
Goal: LLM-free generated drills (percentages, breakevens, growth, big-number division) with timing and results stored.
Files: `app/engine/drills.py`, CLI + web hooks.
Depends: T-020.
Accept: fully functional offline; results feed coverage.
Tests: generation ranges, grading, storage.

**T-064 · Benchmark flashcards** `[ ]`
Goal: flashcard drill over benchmarks.json, LLM-free.
Files: `app/engine/drills.py` (extend), `web/`.
Depends: T-063, T-013.
Accept: cards sourced live from benchmarks.json; offline-functional.
Tests: card generation from fixture benchmarks.

**T-065 · Standard + cold modes + hints** `[ ]`
Goal: cold mode (no hints, pacing pressure), hints with score cost in standard/cold, wired to graduation.
Files: `app/engine/case_flow.py` (extend), scoring hook.
Depends: T-061.
Accept: hint usage recorded and costed in scorecard; cold mode reachable only via graduation rule (recommendation-level, not a hard lock).
Tests: hint costing; mode gating recommendation.

**T-066 · check_limits script** `[ ]`
Goal: print per-provider remaining headroom from live headers.
Files: `scripts/check_limits.py`.
Depends: T-028.
Accept: usable pre-session; no key leakage in output.
Tests: formatting from fixture headers.

---

## Cross-cutting (schedule alongside phases as listed)

**T-070 · Prompt regression suite** `[ ]` (with Phase 1 personas, extend each persona change)
Goal: `scripts/run_regression.py` per 07_PROMPTS §6.
Files: `scripts/run_regression.py`, `tests/regression/inputs/`.
Depends: T-015, T-019.
Accept: 10-15 canned inputs per persona; violation checks (leaked solution, invented numbers, broken character, coach answers-before-attempt); runnable against live Groq with daily-budget warning.
Tests: violation detectors unit-tested against canned bad outputs.

**T-071 · Chaos check procedure** `[ ]` (each phase gate from Phase 2)
Goal: documented, semi-automated Wi-Fi-kill test asserting graceful degradation.
Files: `docs/chaos-check.md`, optional helper script.
Depends: T-028.
Accept: procedure executed and result noted at each gate tag.
Tests: n/a (procedure); router degradation already covered by T-028 tests.

**T-072 · app.db backup job** `[ ]` (any time after T-020)
Goal: nightly launchd copy to iCloud Drive or external folder.
Files: `scripts/backup_launchd.plist`, install notes in README.
Depends: T-020.
Accept: job installed; a dated copy exists after one cycle.
Tests: manual verification checklist.

---

## Content sessions (not code tasks; tracked for sequencing)

**T-C1 · Seed content** `[ ]` — per 05 §Session C1 and 03_CONTENT_SPEC §5. Blocks: T-019 exit (needs real content to hit Phase 1 gate).
**T-C2 · Content expansion** `[ ]` — per 05 §Session C2. Blocks: Phase 5 exit quality (dashboard needs history breadth, not strictly code-blocked).
