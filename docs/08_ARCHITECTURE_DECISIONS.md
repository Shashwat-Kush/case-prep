# 08_ARCHITECTURE_DECISIONS: ADR Log

The record of why the system is shaped the way it is. Statuses: Accepted. New decisions made during implementation get appended here (or proposed in `docs/decisions.md` first, per 04_ENGINEERING_RULES §10). Do not re-litigate accepted ADRs in code review; supersede them with a new ADR if circumstances change.

---

## ADR-1: The LLM roleplays and teaches; it does not author live

**Context.** LLMs improvising case facts contradict themselves within minutes and make grading incomparable across sessions. This was a survival requirement when a 3B local model was the plan; with 70B-class cloud models it remains the consistency and fairness guarantee.
**Decision.** All case facts, lesson content, guesstimate trees, benchmarks, model answers, and rubrics are pre-written content files. The model restates, reveals, and grades against file content only.
**Relaxation.** The LLM may help draft content files offline (C-sessions), subject to validator recomputation and a human read-through. It still never invents facts mid-session.
**Consequences.** Content authoring is the project's long pole; the app gains reproducible sessions and comparable scores. See 03_CONTENT_SPEC.

## ADR-2: The backend owns the state machine, not the model

**Context.** Models drift when asked to track phase, unlocked data, and timing across turns; long contexts also burn tokens-per-minute budget.
**Decision.** Phase, unlocked exhibits, ladder position, and elapsed time are tracked in Python. Each LLM call receives only current-step instructions plus a recent transcript window.
**Consequences.** Prompts stay small and calls stay inside token/min caps; flows are testable without a model; prompt text never encodes state logic (07_PROMPTS §1).

## ADR-3: Math is checked deterministically

**Context.** LLMs grade arithmetic unreliably and generously; case prep lives and dies on math accuracy.
**Decision.** Python parses stated numbers and checks them against case checkpoints or guesstimate segment values with tolerances. The LLM only communicates verdicts and comments on approach.
**Consequences.** Requires a number-parsing spec (REVIEW_REPORT G-4) and, with voice, a number confirmation step to keep STT errors out of the checker.

## ADR-4: Voice is a layer, not a foundation

**Context.** Voice is the fiddliest integration; coupling the core loop to it risks the whole project.
**Decision.** Everything works typed first. Voice (push-to-talk STT, TTS) bolts on at V1 and degrades back to typed/text on any failure.
**Consequences.** Phase 1-3 ship without audio; speech failures are degradations, never session failures (04_ENGINEERING_RULES §5).

## ADR-5: Provider abstraction from day one

**Context.** The product depends on free tiers that can change limits or deprecate models; three providers (Groq, Nvidia, Ollama) all speak the OpenAI-compatible API.
**Decision.** One LLM client with base URL, model, and key from config. Provider order Groq → Nvidia → Ollama. Failover on 429-after-retries, network errors, or daily-cap errors. Nothing outside `app/providers/` knows provider specifics.
**Consequences.** Config-only model swaps; mandatory router tests before cloud code merges; per-call provider recorded for observability.

## ADR-6: Big calls are budgeted

**Context.** End-of-case scoring wants the full transcript (5-10K tokens), which can exceed per-minute token caps in one call, while interview turns stay small by ADR-2.
**Decision.** Scoring runs as 2-3 sequential chunked calls (one per rubric group), honors retry-after between chunks, and may target whichever provider has headroom. Any new LLM call type must state its worst-case token cost.
**Consequences.** Scoring is slightly slower and needs an orchestrator, in exchange for never tripping caps mid-feedback.

## ADR-7: Cloud is a dependency, treated honestly

**Context.** The default profile sends practice transcripts through Groq/Nvidia and requires internet.
**Decision.** Accept the dependency; document it; keep content and progress local; provide an offline profile (Ollama + typed + LLM-free drills) as one config switch at reduced quality. Mid-session network loss must degrade, not crash.
**Consequences.** Chaos check at each phase gate; provider status surfaced in UI; privacy posture stated in PRD risks.

## ADR-8: Content as data; conversion stays out of the app

**Context.** Building PDF ingestion into the app adds a large, brittle surface for a one-time-ish need; conversion quality needs judgment anyway.
**Decision.** The app ships zero PDF/extraction code. Content folders are the database of record for content; the folder is the manifest (no index file). SQLite holds only user data, linked by content id. All conversion from source books happens in C-sessions with Claude; only validated JSONs enter the repo.
**Consequences.** Adding content = dropping a file; the loader validates and skip-with-warns; C-sessions appear in the implementation plan as first-class work items; uploads must be re-provided each C-session since they don't persist between Claude conversations.

## ADR-9: Learn before perform, per topic

**Context.** The user is a beginner; cold realistic interviews first would measure nothing and discourage plenty.
**Decision.** Default flow per topic: lesson → drill → guided → standard → cold (guesstimates: coached → timed), enforced softly through recommendations, never locks. Feedback tone and score visibility follow the stage: coach tone and hidden scores early, evaluative scores from standard mode onward, graduation rules in config.
**Consequences.** Guided mode and coach persona are MVP; a diagnostic session seeds the ladder; the dashboard's primary object is concept coverage, with score trends layered on later.
