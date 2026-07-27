# REVIEW_REPORT: Documentation Review Findings

Issues found while reorganizing the v3 specification into the documentation system. Nothing here changes the project; each item carries a recommendation and, where relevant, the task it blocks. IDs: I-n inconsistencies, G-n gaps/ambiguities, N-n notes.

## Inconsistencies (fix or explicitly accept)

**I-1 · Validator name vs scope.** `scripts/validate_case.py` validates all four content types (cases, guesstimates, lessons, benchmarks), and the original spec kept the name for continuity. Misleading for agents grepping by name.
Recommendation: rename to `validate_content.py` at T-012 and record the rename in `docs/decisions.md`; docs currently preserve the original name and flag it (03_CONTENT_SPEC §4).

**I-2 · "Difficulty levels" vs modes.** The spec uses guided/standard/cold both as per-case "difficulty levels" (V2 feature, Module A) and as session modes (MVP/V1). These are different things: modes are how you run a case; `meta.difficulty` is content metadata.
Resolution applied in docs: modes are modes (MVP/V1 per PRD Module A); per-case difficulty stays metadata; the V2 "difficulty levels" row is retained as metadata-driven filtering only. No feature removed.

**I-3 · Timed guesstimates persona.** PRD Module J puts timed mode at V1; 07_PROMPTS assigns timed guesstimates to the interviewer persona also marked for interviewer-led flow at V1. Consistent, but the guesstimate rubric's coach-tone feedback vs interviewer-mode delivery is unspecified for timed runs.
Recommendation: timed mode uses interviewer persona during the run and standard evaluative feedback after; confirm at T-022 follow-up.

## Gaps and ambiguities (settle before the blocked task)

**G-1 · Exhibit `unlock_condition` format is unspecified.** Options: keyword/intent match by the LLM ("user asked about costs"), explicit phase-based unlock, or a hybrid. Pure LLM-judged unlocking reintroduces model judgment into state (tension with ADR-2).
Recommendation: phase-scoped whitelist + LLM intent classification returning a constrained label, decided by the backend. Blocks: T-016.

**G-2 · Frontend stack and streaming transport undecided.** React vs plain HTML/JS; SSE vs WebSocket. The original spec deliberately deferred this.
Recommendation: plain HTML/JS + SSE for one-user simplicity unless the notes scratchpad and dashboard argue for React. Settle at Phase 3 start. Blocks: T-040.
**SETTLED (2026-07-28, T-040): plain HTML/JS + SSE.** One-directional token streaming (browser POSTs a turn, server streams the reply) is all the case loop needs; no WebSocket bidirectionality, no build step. Revisit only if the dashboard (T-062) demands a component framework. See docs/decisions.md.

**G-3 · "Recent transcript window" size undefined.** ADR-2 depends on it; token/min math (02_ARCHITECTURE §3) assumes trimming but no number exists.
Recommendation: config default of last 12 turns or ~2,000 tokens, whichever is smaller; tune during Phase 1. Blocks: T-016 (weakly).

**G-4 · Number-parsing spec missing.** The math checker's contract (ADR-3) needs a defined grammar: Indian groupings (1,50,000), lakh/crore, million/billion, percentages, currency symbols, ranges ("40 to 50"), and spoken-number artifacts post-STT.
Recommendation: write the grammar as a table of accepted forms with test vectors before T-023; it doubles as the T-052 cleanup spec. Blocks: T-023, T-052.

**G-5 · "5 consecutive clean runs" is unmeasured.** MVP success criterion (PRD §8) has no definition of "clean."
Recommendation: define as: no crash, no validator-detectable fact contradiction by the interviewer, no regression-suite violation in sampled outputs, flow completes all phases. Add a checklist to `docs/chaos-check.md` or a sibling doc.

**G-6 · Mid-session content edits.** Loader refresh swaps the library atomically, but behavior when a live session's backing file changes is unspecified.
Recommendation: sessions pin the content object at start (in-memory reference); refresh affects new sessions only. One sentence in T-013's implementation. Blocks: T-013 (trivially).

**G-7 · Scoring JSON contract.** 07_PROMPTS §5 mandates strict JSON from the scoring prompt but the schema (dimensions, quote fields, chunk boundaries) isn't written.
Recommendation: define the scorecard pydantic model first (it exists implicitly in T-025) and derive the prompt's required output from it. Blocks: T-025.

**G-8 · Quiz grading split.** T-017 says "deterministic where options exist, via rubric prompt where free-form," but free-form quiz grading has no rubric structure in the lesson schema (03_CONTENT_SPEC §2.3 has `answer` + `explanation` only).
Recommendation: for MVP restrict quizzes to option-based questions; add a free-form rubric field to the lesson schema only if needed later. Blocks: T-017.

**G-9 · Diagnostic guesstimate count vs library.** The diagnostic uses 2 guesstimates; the seed set has 3. Which 2, and are they excluded from the practice ladder afterward?
Recommendation: flag 2 of the 3 as `diagnostic: true`; diagnostic content is excluded from ladder recommendations but stays browsable. Blocks: T-027, T-C1.

**G-10 · Ladder rules format.** "Ladder rules in config" is asserted (02_ARCHITECTURE §6) but no rule syntax exists.
Recommendation: keep it to a fixed, code-defined rule set with config-tunable thresholds (e.g. `graduation_min_avg: 3.0`), not a rule DSL. Blocks: T-061.

**G-11 · Benchmarks maintenance.** `as_of` exists per key but nothing defines when or how benchmarks get refreshed, and stale benchmarks silently skew every guesstimate.
Recommendation: a yearly C-session line item; validator warns (not fails) when `as_of` is more than 2 years behind the current year.

**G-12 · Whisper model variant unpinned.** English-only vs multilingual interacts with PRD open question 3.
Recommendation: settle question 3 first; if English-only, request the English-optimized model in the STT call where the API allows. Blocks: T-051 (weakly).

## Notes (no action required)

**N-1 · Estimates are unchanged but soft.** 10-15 build sessions + 2-3 C-sessions carried over from v3 verbatim; treat as planning fiction until Phase 1 actuals exist.
**N-2 · Provider limit figures are indicative by design.** All docs cite approximate limits and defer to Phase 0 verification in `docs/decisions.md`; this is intentional, not vagueness.
**N-3 · Nvidia terms.** Single-owner personal use sits inside dev/test/evaluation terms; the PRD non-goal (serving others) is the guardrail. Revisit only if the product's audience ever changes.
**N-4 · Engineering handbook additions.** 04_ENGINEERING_RULES §1, 3, 4, and 13 introduce standards (ruff, DI conventions, naming, agent rules) that were implicit or absent in v3. They are process standards, not product changes, added per the reorganization mandate.
**N-5 · Duplication removed.** Provider limits now live only in 02_ARCHITECTURE §3; schemas only in 03_CONTENT_SPEC §2; phase gates only in 05_IMPLEMENTATION_PLAN; D1-D9 rationale only in 08 (other docs reference ADR-n). The v3 monolith remains the historical source; these docs supersede it.
