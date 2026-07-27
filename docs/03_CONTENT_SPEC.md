# 03_CONTENT_SPEC: Content System

The single source of truth for content schemas, validation, loading behavior, and the source-book pipeline. Feature-level intent for content-driven modes is in [01_PRD.md](01_PRD.md) (Modules A, I, J, F); loader placement in the system is in [02_ARCHITECTURE.md](02_ARCHITECTURE.md) §2 and §6; the rationale is ADR-1 and ADR-8 in [08_ARCHITECTURE_DECISIONS.md](08_ARCHITECTURE_DECISIONS.md).

## 1. Content model

Content is data on disk, never code. Four types live in version-controlled folders; the folder is the manifest (no index file to keep in sync). The app ships zero PDF or extraction code; all conversion from source books happens in C-sessions with Claude, and only validated JSONs enter the repo. SQLite stores user data only, linked to content by content `id`, so content can be added, edited, or deleted without touching history.

Content `id` values must be unique across all content types (they key progress records).

## 2. Schemas

Implement these as pydantic models in `app/engine/`; the models are the executable form of this spec. Fields marked (opt) are optional.

### 2.1 `cases/<id>.json`

```
meta: id, title, type, industry, difficulty, est_minutes,
      prerequisite_concepts: [lesson ids], diagnostic: bool (opt)
prompt:      opening statement read by interviewer
clarifying:  [{question_pattern, answer}]
facts:       ground-truth key/value facts the interviewer may share
exhibits:    [{id, title, data, unlock_condition, so_what}]
phases:      [{name, interviewer_instructions,
              coaching: {explain, model_approach_for_phase},
              time_budget, pass_criteria}]
math_checkpoints: [{inputs, expected_value, tolerance, common_errors}]
curveballs (opt): [{trigger_phase, injected_fact}]
model_answer: framework, key_insights, recommendation, walkthrough
rubric:      per dimension (structure, math, judgment, communication,
             synthesis): anchors for scores 1-5 with example phrases
```

Notes: `coaching` powers guided mode; a case without it supports standard/cold only. `so_what` is the insight a strong candidate extracts from the exhibit; feedback uses it. `phases[].name` values follow the case flow in 02_ARCHITECTURE §5.

### 2.2 `guesstimates/<id>.json`

```
meta: id, title, difficulty, est_minutes, region, diagnostic: bool (opt)
prompt, clarifications
approach: {recommended: top_down|bottom_up,
           tree: [{segment, benchmark_refs: [benchmark keys],
                   derivation, value, tolerance}]}
answer_range: {low, high}
common_traps: []
rubric: approach, segmentation, arithmetic, sanity_check
```

Notes: every `benchmark_refs` entry must exist in `benchmarks.json`; segment `value`s must be derivable from their refs and `derivation`.

### 2.3 `lessons/<id>.json`

```
meta: id, title, concepts_taught: [], order_hint
sections: [{heading, content, worked_example}]
when_to_use, when_not_to_use
quiz: [{question, options (opt), answer, explanation}]
```

Notes: `concepts_taught` values are what cases reference in `prerequisite_concepts`; keep them stable once published.

### 2.4 `benchmarks.json`

```
{key: {value, unit, as_of, source_note}}
e.g. india_population: {value: 1.45e9, unit: "people",
                        as_of: 2026, source_note: "..."}
```

The single canonical facts file. Every guesstimate and case references it; no content file may restate a benchmark with a different value.

## 3. Loading behavior (app-side contract)

- The content loader scans the four locations at startup and on explicit refresh.
- Every file is validated (same checks as the CLI validator, §4). Valid files enter the in-memory library; invalid files are **skipped with a visible warning** naming the file and the failed check. Loading never crashes the app.
- Refresh atomically swaps the library. Behavior when a file backing a live session changes mid-session is currently unspecified: see REVIEW_REPORT G-6.

## 4. Validation

`scripts/validate_case.py` validates **all four content types** despite its name (naming flagged in REVIEW_REPORT I-1). It runs as a pre-commit hook and its checks are shared with the loader:

1. Schema conformance (pydantic)
2. Recompute every case `math_checkpoint` from its inputs; must equal `expected_value` within `tolerance`
3. Recompute every guesstimate tree: segment values from `benchmark_refs` + `derivation`; tree must aggregate into `answer_range`
4. Every `benchmark_refs` key exists in `benchmarks.json`
5. Every exhibit referenced by a phase exists; every `prerequisite_concepts` lesson id exists
6. `id` uniqueness across all content

LLM-drafted content additionally requires a human read-through before entering the repo (ADR-1 relaxation applies to drafting only, never to live sessions).

## 5. Source pipeline: books → content

Conversion happens outside the app in C-sessions (ADR-8): the user re-uploads the source PDFs (uploads don't persist between Claude conversations), Claude drafts JSONs in batches, the validator recomputes all math, the user spot-checks, files enter the repo.

| Source | Format | Feeds | Conversion notes |
|---|---|---|---|
| Harsh Saraf handwritten notes (16 pp) | Scanned handwriting | Lessons (profitability, market entry, pricing, growth, value chain, MTP, sales force, guesstimate method); benchmark candidates | Manual transcription by Claude reading the scans; not automatable. One session. |
| Guess-It-Matters, IIT Guwahati (30 pp) | Clean digital text | Guesstimate bank (~20 solved questions); assumptions page seeds benchmarks.json | Best direct-conversion source. One sitting. |
| Day One, IIT Madras (206 pp) | Digital text | Lessons (concept explanations); fit/PEI content (V2) | 2015 vintage: concepts fine, all numbers stale, none enter benchmarks.json. Convert selectively. |
| CIC IITB Cracked Case Interviews (208 pp) | Digital text | Case library (worked cases → case JSONs) | Primary case feedstock. Batch 3-4 cases per session. Some cases need data reconstructed into exhibit tables. |

**Benchmark reconciliation (one-time, in session C1):** sources disagree (e.g. India population 1.2B in the notes vs 1.4B in the IIT G book). One pass produces canonical `benchmarks.json` with current-year values; every converted file references it, and stale source numbers are updated to canonical values during conversion.

**Seed content set (session C1, MVP):** `benchmarks.json`; 2 lessons (case interview basics, profitability tree) from the Saraf notes; 3 guesstimates from IIT G; 2 cases from CIC IITB, one with a full coaching block, one flagged `diagnostic`.

**Expansion (session C2+):** remaining IIT G guesstimates; 3-4 more CIC cases per session; 2-3 more lessons. Target library: ~8 lessons, 15-20 cases, ~20 guesstimates.

## 6. Licensing

The IIT M Day One book is explicitly licensed free for personal use. The other sources are for private use. Converted JSONs live in a private repo and are never redistributed.

## 7. Authoring guide

`docs/content-authoring-guide.md` in the repo carries worked examples of each schema for future authoring (human or Claude-assisted). Keep it in sync with the pydantic models; the models win on conflict.
