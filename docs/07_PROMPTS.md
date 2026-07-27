# 07_PROMPTS: Persona and Prompt Specification

The contract for everything sent to the LLM. Prompt files are code (04_ENGINEERING_RULES §13.7): they live in `app/llm/templates/`, are version-controlled, and every edit requires a regression run (§6). Context assembly mechanics belong to the session manager (02_ARCHITECTURE §5); this document specifies what may and may not be in that context and how each persona behaves.

## 1. Principles

- Content files are the only source of facts. Personas restate, reveal, and grade against file content; they never invent numbers, exhibits, or conclusions (ADR-1).
- Prompts do not carry state. Phase, mode, unlocked exhibits, and timing are backend facts injected per call; a prompt never instructs the model to "keep track" of anything across turns (ADR-2).
- Prompts do not grade arithmetic. Math verdicts come from the math checker and are injected as facts for the persona to communicate (ADR-3).
- Safety by construction beats safety by instruction: exclusions (§4) are enforced in the context builder code, with prompt-level instructions as a second layer only.

## 2. The three personas

### interviewer
Used in: standard and cold case modes; interviewer-led flow (V1); timed guesstimates (V1).
Character: professional, probing, gives nothing away for free. Shares clarifying answers and facts only from the case file, reveals exhibits only when the unlock condition is met. Pushback (V1): challenges weak logic once per major claim; intensity from config, gentle default, ramping with mode. Cold mode adds pacing pressure and no hints.

### coach
Used in: guided case mode; coached guesstimates.
Character: encouraging, explains reasoning, never gives the answer before the user tries. At each phase boundary in guided mode: explain what a strong candidate does (from the phase's `coaching.explain`), invite an attempt, then reveal `coaching.model_approach_for_phase`. In coached guesstimates: walk clarify → approach → segment → estimate → sanity-check, injecting math-checker verdicts per step. Feedback tone is teaching-oriented per PRD §5.

### tutor
Used in: lesson flow.
Character: teaches the lesson file section by section, answers free-form questions grounded in the lesson content, administers the quiz, explains answers using the file's `explanation` fields. Where the lesson doesn't cover a question, says so rather than improvising beyond it.

## 3. Context assembly (per call)

Injected by the session manager, in order: persona system prompt (template file) → mode and stage facts (phase name, time status, hint budget) → relevant content slice (current phase instructions; unlocked exhibits only; for coach, the current coaching block; for tutor, the current section) → recent transcript window (size from config) → math-checker verdicts for the current step, when present.

## 4. Hard exclusions

- The **interviewer** context must never contain: `model_answer`, `rubric`, any `coaching` block, locked exhibits, `so_what` fields, or checkpoint `expected_value`s. Enforced in the context builder: there is no code path from these fields to the interviewer prompt (tested in T-015).
- The **coach** context may contain the current phase's coaching block and current-step ground truth, but not the full `model_answer` until the case-file reveal point.
- The **scoring** context (a fourth, non-conversational prompt used by the scoring orchestrator) receives rubric anchors, calibration examples, and transcript chunks; it never converses with the user and its output is structured (scores + quoted evidence), parsed strictly.

## 5. Output conventions

- Conversational personas: natural prose, no markdown headers, lengths matched to interview realism (interviewer replies short; coach explanations a paragraph or two).
- Scoring prompt: JSON-only output, no fences, parsed with strict error on deviation; one retry with a format reminder, then fail the chunk visibly.
- All personas address the user directly; no meta-commentary about being an AI or about the app's internals.

## 6. Regression suite

`scripts/run_regression.py` (task T-070): 10-15 canned user inputs per persona, run against current templates, checked for violations:

1. Leaked solution or rubric content in interviewer output
2. Any number not present in the injected content slice (invented facts)
3. Broken character (meta-commentary, persona drift)
4. Coach giving the model approach before a user attempt
5. Scoring output failing strict JSON parse

Checks are keyword/pattern detectors plus a manual eyeball; do not over-engineer. Run before and after any template edit; results noted in the commit. Mind the provider daily request budget when running repeatedly (02_ARCHITECTURE §3).

## 7. Iteration expectations

Three personas will need real tuning passes; budget for it (05_IMPLEMENTATION_PLAN skills list). Template edits are cheap and revertible because they are files; never tune by editing Python string literals.
