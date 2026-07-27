# 01_PRD: Product Requirements

What CasePrep Local is, who it serves, and what it must do. For system shape see [02_ARCHITECTURE.md](02_ARCHITECTURE.md); for the reasoning behind constraints see [08_ARCHITECTURE_DECISIONS.md](08_ARCHITECTURE_DECISIONS.md); for schemas see [03_CONTENT_SPEC.md](03_CONTENT_SPEC.md).

## 1. Problem statement

The user is starting case interview prep from zero. Practicing alone with a book gives no interaction and no feedback; live partners and coaching are expensive. They need to be taught the craft (case types, frameworks, structuring, case math, guesstimate technique), then drilled, then tested under realistic interview conditions, with honest scored feedback and progress tracking, at zero recurring cost on their own machine.

## 2. Target user

One user, a beginner to case interviews, preparing for consulting-style interviews at Indian B-schools and firms. Needs candidate-led and interviewer-led case styles plus standalone guesstimate rounds. No accounts, no multi-tenancy, no auth.

## 3. Goals

1. Teach case solving from zero: concepts, frameworks, case math, guesstimate technique
2. A progression ladder from guided practice to cold realistic interviews
3. Realistic mock interviews with a 70B-class interviewer persona
4. A dedicated guesstimate mode grading the approach, not just the final number
5. Voice-first interaction with typed fallback
6. Reliable facts and math: pre-written content files, deterministic math checking
7. Progress tracking that knows what the user hasn't learned yet, not just scores
8. Zero recurring cost via free API tiers, with an offline fallback profile

## 4. Non-goals

- Multi-user support, accounts, cloud sync, mobile app
- Video/webcam analysis; reading handwritten paper frameworks (user types or describes structures)
- Live case generation by the LLM during interviews (ADR-1)
- PDF ingestion or conversion features inside the app (ADR-8)
- Serving anyone but the owner (also keeps Nvidia dev/test terms satisfied; see 02_ARCHITECTURE §3)

## 5. The learner journey

The product has three layers the user moves through per topic, not globally:

```
LEARN  ->  DRILL  ->  PERFORM
lessons    isolated    guided case -> standard case -> cold case
+ quiz     reps        (guesstimates: coached -> timed)
```

- **Diagnostic baseline (first session):** one short assessment case plus 2 guesstimate questions, zero stakes, scores recorded but hidden. Seeds the dashboard and tells the tool what to teach first.
- **Progression ladder:** the home screen recommends the next step (e.g. "you've done the profitability lesson and drill; try the guided profitability case"). The full library stays browsable; the ladder is the default path, not a lock.
- **Graduation criteria per topic:** a standard case at 3+/5 average unlocks the cold version. Simple rules in config, no ML.
- **Feedback tone by stage:** teaching-oriented in guided mode; evaluative scores from standard mode onward. Score visibility is a config flag, hidden by default for the first 3 sessions.

## 6. Feature specification

Priorities: **MVP**, **V1**, **V2**, **Later**. Module letters are stable identifiers used across all docs and the task queue.

### Module I: Learning

| Feature | Priority | Notes |
|---|---|---|
| Lesson files: concept explanation, worked example, when-to-use / when-not, quiz | MVP | First lessons: what a case interview is, the phase flow, profitability tree, guesstimate method. Sourced per 03_CONTENT_SPEC §5. |
| Tutor persona teaching a lesson interactively, answering questions, running the quiz | MVP | Same LLM pipeline, different system prompt (07_PROMPTS). Lesson file is ground truth. |
| Diagnostic baseline session | MVP | A flagged case + guesstimate pair, scores recorded but hidden. |
| Progression ladder + next-step recommendation | V1 | Rules engine over progress data. |
| Framework library reference page | V1 | Browse frameworks outside lesson flow. |
| Quiz-only quick reviews of past lessons | V2 | |

### Module A: Case engine

| Feature | Priority | Notes |
|---|---|---|
| Case file schema (03_CONTENT_SPEC §2.1) incl. coaching block and prerequisite_concepts | MVP | `coaching` powers guided mode; `prerequisite_concepts` links cases to lessons for the ladder. |
| Guided mode: interviewer pauses each phase, coaches, lets the user try, reveals the model approach for that phase | MVP | The beginner's first playable mode. |
| Standard mode (candidate-led, normal interviewer) | MVP | |
| Cold mode (no hints, realistic pacing pressure) | V1 | Graduation target. |
| Staged exhibit reveal, gated by unlock conditions in the case file | MVP | |
| Case state machine owned by backend | MVP | ADR-2. |
| Interviewer-led (McKinsey style) flow | V1 | Different flow, same case files. |
| Hints system with score cost (standard/cold modes) | V1 | |
| Timer with phase pacing; overruns noted in feedback | V1 | |
| Curveballs: mid-case fact changes defined in the case file | V2 | |
| Difficulty levels per case (guided/standard/cold are modes; per-case difficulty is metadata) | V2 | |

### Module J: Guesstimates

| Feature | Priority | Notes |
|---|---|---|
| Guesstimate schema: prompt, clarifications, approach tree, benchmark refs, answer range, traps (03_CONTENT_SPEC §2.2) | MVP | Simpler than cases; one flow, no exhibits. |
| Shared `benchmarks.json`, single source of truth for all content | MVP | Reconciled once from source books (03_CONTENT_SPEC §5). |
| Coached mode: clarify → approach → segment → estimate → sanity-check, step by step | MVP | Beginner entry point. |
| Timed mode (10-15 min) | V1 | |
| Approach-graded scoring: structure and segmentation scored by rubric, arithmetic checked deterministically, final number checked against range | V1 | A sound path outweighs a lucky number; the rubric encodes that. |
| Benchmark memorization drill (flashcards, no LLM) | V1 | |
| Question bank ~20 questions | MVP for first 5, V1 for the rest | |

### Module B: Interviewer/tutor persona

| Feature | Priority | Notes |
|---|---|---|
| Interviewer persona (standard/cold) | MVP | Spec in 07_PROMPTS. |
| Coach persona (guided mode, lessons, coached guesstimates) | MVP | Explains reasoning, never gives answers before the user tries. |
| Pushback behavior, configurable intensity | V1 | Gentle default for a beginner; ramps with mode. |
| Firm-style toggle; PEI/fit mode | V2 | Fit content sourced from the Day One book. |

### Module C: Feedback and scoring

| Feature | Priority | Notes |
|---|---|---|
| End-of-case scorecard: structure, math, judgment, communication, synthesis (1-5 each) | MVP | Visibility per §5. |
| Evidence-based feedback quoting the user's actual words | MVP | Requires full transcript retention. |
| Model answer reveal (pre-written, never generated) | MVP | |
| Deterministic math checking | V1 | ADR-3. |
| Chunked scoring | V1 | ADR-6. |
| Scoring calibration anchors (examples of 2/5 vs 4/5 per dimension) | V1 | Grade inflation shrinks with model size but doesn't vanish. |
| "What to study next" line linking feedback to a lesson | V1 | Closes the learn-drill-perform loop. |
| Per-phase micro-feedback toggle | V2 | Off by default; interrupting flow hurts realism. |

### Module D: Drills

| Feature | Priority | Notes |
|---|---|---|
| Mental math sprints (percentages, breakevens, growth, big-number division) | V1, scheduled early | Pure Python, offline, no API. A beginner needs these reps immediately. |
| Benchmark flashcards | V1 | |
| Structure-in-90-seconds drills | V2 | |
| Chart/exhibit interpretation drills | V2 | |

### Module E: Voice

| Feature | Priority | Notes |
|---|---|---|
| Typed-chat fallback always available | MVP | Also the interface before voice exists (ADR-4). |
| Push-to-talk mic capture in browser | V1 | Push-to-talk, not open mic: no VAD tuning, no accidental capture. |
| STT via Groq hosted Whisper | V1 | |
| TTS via Piper, local | V1 | One voice, kept consistent. |
| Number-aware transcript correction + UI confirm step for stated numbers | V1 | Protects the math checker from STT errors. |
| Local whisper.cpp fallback | V2 | Only needed for offline voice; defer. |
| Barge-in (interrupt mid-sentence) | Later | |

### Module F: Content library (app-side behavior; schemas and pipeline live in 03_CONTENT_SPEC)

| Feature | Priority | Notes |
|---|---|---|
| File-based content loading with validation, skip-with-warning | MVP | ADR-8. |
| Library browser with filters + ladder recommendations | V1 | |
| Initial content set: 2 lessons, 2 cases (1 with coaching block), 3 guesstimates, benchmarks.json, diagnostic flag | MVP | Produced in session C1 (05_IMPLEMENTATION_PLAN). |
| Full content set: ~8 lessons, 15-20 cases, ~20 guesstimates | V2 | Ongoing C-sessions. |

### Module G: Progress tracking

| Feature | Priority | Notes |
|---|---|---|
| Session log in SQLite: transcripts, scores, timing, provider, mode | MVP | |
| Concept coverage map: lessons done, case types attempted at which mode | V1 | What "progress" means for a beginner before score trends mean anything. |
| Score trends per dimension | V1 | |
| Weakness flags + next-step recommendation feed | V1 | |
| Smart case suggestion; spaced repetition | Later | |

### Module H: UI

| Feature | Priority | Notes |
|---|---|---|
| Terminal chat interface | MVP | Phase 1 proves the loop. |
| Local web app: chat pane, exhibit viewer, timer, notes scratchpad | V1 | |
| Provider status indicator (live provider, remaining headroom from rate-limit headers) | V1 | |
| Lesson reader and guesstimate step view | V1 | |
| Session review screen: transcript with inline feedback annotations | V1 | |
| Dashboard with ladder view; home screen is "continue where you left off" | V1 | |
| Dark mode, keyboard shortcuts, polish | V2 | |

## 7. Product risks

Engineering and operational mitigations are specified in [02_ARCHITECTURE.md](02_ARCHITECTURE.md) and [04_ENGINEERING_RULES.md](04_ENGINEERING_RULES.md); this table owns the product-level risk register.

| Risk | Severity | Mitigation |
|---|---|---|
| Content conversion stalls the project (lessons + cases + guesstimates is a large surface) | High | Thin MVP content set; batched C-sessions; validator automates math checking; IIT G book converts in one sitting for an early win |
| Beginner discouragement from harsh early feedback | Medium | Coach persona, hidden scores early, guided mode first (ADR-9) |
| Ladder feels like a cage | Low | Recommendations not locks; library always browsable |
| Free-tier limits change or a model is deprecated | Medium | Provider abstraction (ADR-5); config-only swaps; verified limits recorded at Phase 0 |
| 429s mid-session break immersion | Medium | Retry-after backoff, failover chain, provider status in UI |
| Whisper mistranscribes numbers, poisoning math checks | High | Number confirmation step, transcript cleanup pass, push-to-talk |
| Benchmarks drift or conflict across content | Medium | Single benchmarks.json; validator flags missing benchmark refs |
| Malformed hand-added JSON breaks the app | Medium | Validation on load, skip-with-warning, never crash |
| Privacy: practice transcripts transit cloud providers | Low-Med | ADR-7; offline profile |
| Scope creep | High | Hard phase gates (05_IMPLEMENTATION_PLAN) |

## 8. Success criteria

- **MVP:** complete the diagnostic; complete one lesson with quiz; complete one guided case end to end where the coach references the lesson's framework; complete one coached guesstimate with arithmetic verified at each step; all typed; 5 consecutive clean runs.
- **V1:** full voice case with under 3 seconds median response gap; math checker catches a planted wrong calculation; ladder recommends a sensible next step after 5 sessions; dropping a new valid case JSON into the folder makes it appear in the library; dropping an invalid one produces a warning, not a crash; Wi-Fi off mid-session degrades gracefully to the offline profile.
- **Ongoing:** the user can feel themselves moving up the ladder, and chooses this tool over the PDFs it was built from.

## 9. Open questions

To settle before Phase 1 (suggested defaults in parentheses):

1. Scoring scale: 1-5 per dimension? (yes)
2. Streaming from Phase 1? (yes; it changes how prompts get tuned)
3. English-only? (affects Whisper model choice and prompt language)
4. Groq default model: 70B everywhere, or a smaller model for lesson chat? (70B everywhere first; Groq is fast enough)
5. Diagnostic length: one mini-case + 2 guesstimates, ~30 min, as session one? (yes; shorter risks a useless baseline)
6. Which 2 seed cases from the CIC IITB book? (pick a profitability and a market entry case during session C1)
