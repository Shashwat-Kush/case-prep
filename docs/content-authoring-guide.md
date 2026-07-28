# Content Authoring Guide

Worked, validated examples of every content type, plus the upload workflow. This
guide tracks the pydantic models in [`app/engine/content_models.py`](../app/engine/content_models.py);
**the models win on any conflict** (03_CONTENT_SPEC §7). The rules here restate
03_CONTENT_SPEC §2–§4 and the recompute conventions settled in
[`decisions.md`](decisions.md).

Every JSON below is copied from a fixture the validator already accepts
(`tests/fixtures/content/valid/`), so each is a safe template to copy and edit.

---

## 1. How content gets in: the C-session workflow

Content is **data, never code**, and conversion happens **outside the app** in a
"C-session" — an ordinary Claude chat, not a coding task (ADR-8).

1. **Upload** your source material (the books/scans) *into the chat*. Do **not**
   commit sources to the repo — they are copyrighted/private and `.gitignore`
   excludes raw data. Uploads don't persist between Claude conversations, so
   re-attach them at the start of each C-session.
2. **Draft.** Claude reads the sources and drafts JSON files in small batches
   (e.g. 3–4 cases at a time).
3. **Validate.** The validator recomputes every math checkpoint and guesstimate
   tree and checks all references (§4 below). Nothing with a violation is kept.
4. **Spot-check.** You read the drafts for sense and fidelity to the source
   (ADR-1: a human read-through is required before content enters the repo).
5. **Land.** Valid files are saved into the folders below and committed.

The app **never** ingests PDFs and never authors facts during a live session; it
only restates, reveals, and grades against these files (ADR-1).

### Source → content-type map (03_CONTENT_SPEC §5)

| Source | Feeds | Notes |
|---|---|---|
| Harsh Saraf handwritten notes | lessons, benchmark candidates | Claude transcribes the scans |
| Guess-It-Matters (IIT-G) | guesstimates, benchmark seeds | best direct-conversion source |
| Day One (IIT-M) | concept lessons, PEI (V2) | 2015 vintage — **numbers are stale, none enter `benchmarks.json`** |
| Cracked Case Interviews (CIC IITB) | cases | primary case feedstock; batch 3–4 per session |

---

## 2. Where files live and how they're named

```
cases/<id>.json            one file per case
guesstimates/<id>.json     one file per guesstimate
lessons/<id>.json          one file per lesson
benchmarks.json            single shared facts file (one only)
```

The **folder is the manifest** — there is no index file to keep in sync. Drop a
valid file in and the loader picks it up; a malformed one is skipped with a
warning, never a crash (03_CONTENT_SPEC §3).

**Ids** are `kebab-case`, unique across *all* types, and prefixed by type
(04 §3):

- cases → `case-...`  e.g. `case-cement-profitability`
- guesstimates → `guess-...`  e.g. `guess-petrol-pumps-delhi`
- lessons → `lesson-...`  e.g. `lesson-profitability`
- benchmark keys → `snake_case`  e.g. `india_population`

The filename should match the id (`cases/case-cement-profitability.json`).

---

## 3. Worked examples

### 3.1 `benchmarks.json` — the single source of truth

Every guesstimate (and any case that needs a fact) references this file. No other
file may restate a benchmark with a different value.

```json
{
  "india_population": {"value": 1.4e9, "unit": "people", "as_of": 2026, "source_note": "estimate"},
  "delhi_population": {"value": 2.0e7, "unit": "people", "as_of": 2026, "source_note": "estimate"}
}
```

- **key** — `snake_case`, referenced by guesstimate `benchmark_refs`.
- **value** — a number (`1.4e9` is fine). **unit** — free text.
- **as_of** — the year the value is current for. The validator will (G-11) warn
  when this is more than ~2 years stale.
- **source_note** — where it came from; keep short.

### 3.2 `lessons/<id>.json`

```json
{
  "meta": {
    "id": "lesson-profitability",
    "title": "The profitability tree",
    "concepts_taught": ["profit-tree", "revenue-cost-decomposition"],
    "order_hint": 2
  },
  "sections": [
    {
      "heading": "Profit = Revenue - Cost",
      "content": "Start every profitability case by splitting profit into revenue and cost.",
      "worked_example": "If revenue is 1500 and cost is 1200, profit is 300."
    }
  ],
  "when_to_use": "Declining or unexpectedly low profit.",
  "when_not_to_use": "Market sizing or pure growth questions.",
  "quiz": [
    {
      "question": "Profit equals?",
      "options": ["Revenue - Cost", "Revenue + Cost"],
      "answer": "Revenue - Cost",
      "explanation": "Profit is what remains after costs."
    }
  ]
}
```

- **concepts_taught** — stable labels; these are what the ladder/coverage map
  track. Keep them fixed once published.
- **sections[].worked_example** — optional.
- **quiz** — for MVP keep questions **option-based** (`options` present); the
  tutor grades those deterministically (G-8). `answer` must be one of `options`.

### 3.3 `cases/<id>.json`

```json
{
  "meta": {
    "id": "case-cement-profitability",
    "title": "Cement maker profitability",
    "type": "profitability",
    "industry": "cement",
    "difficulty": "medium",
    "est_minutes": 30,
    "prerequisite_concepts": ["lesson-profitability"],
    "diagnostic": false
  },
  "prompt": "Your client is a cement manufacturer whose profits have fallen. Why?",
  "clarifying": [
    {"question_pattern": "which product", "answer": "A single grade of grey cement."}
  ],
  "facts": {"revenue": 1500, "cost": 1200},
  "exhibits": [
    {
      "id": "ex-cost-breakdown",
      "title": "Cost breakdown",
      "data": {"power": 400, "freight": 500, "other": 300},
      "unlock_condition": "phase:analysis",
      "so_what": "Freight is the largest and fastest-growing cost line."
    }
  ],
  "phases": [
    {"name": "opening", "interviewer_instructions": "Read the prompt, invite structure."},
    {"name": "structuring", "interviewer_instructions": "Probe the candidate's tree."},
    {
      "name": "analysis",
      "interviewer_instructions": "Reveal the cost exhibit when asked about costs.",
      "coaching": {
        "explain": "A strong candidate isolates whether the problem is revenue or cost.",
        "model_approach_for_phase": "Decompose profit into revenue and cost, then drill into cost lines."
      },
      "time_budget": 10,
      "pass_criteria": "Identifies freight as the driver."
    },
    {"name": "synthesis", "interviewer_instructions": "Ask for a recommendation."}
  ],
  "math_checkpoints": [
    {
      "inputs": "(1500 - 1200) / 1500",
      "expected_value": 0.2,
      "tolerance": 0.001,
      "common_errors": ["divided by cost instead of revenue"]
    }
  ],
  "curveballs": [
    {"trigger_phase": "analysis", "injected_fact": "Freight costs jump another 10% next quarter."}
  ],
  "model_answer": {
    "framework": "Profitability tree focused on the cost side.",
    "key_insights": ["Freight is the dominant and rising cost."],
    "recommendation": "Renegotiate freight contracts and consider rail.",
    "walkthrough": "Profit fell because freight rose; revenue was stable."
  },
  "rubric": {
    "structure": {"anchors": {"1": "no structure", "3": "basic tree", "5": "MECE tree tailored to cement"}},
    "math": {"anchors": {"1": "errors", "3": "correct with help", "5": "fast and accurate"}},
    "judgment": {"anchors": {"1": "no insight", "3": "some", "5": "prioritizes freight"}},
    "communication": {"anchors": {"1": "unclear", "3": "clear", "5": "crisp top-down"}},
    "synthesis": {"anchors": {"1": "none", "3": "restates", "5": "actionable recommendation"}}
  }
}
```

Key rules:

- **`coaching` is optional per phase.** A case with coaching blocks supports
  **guided** mode; one without them supports standard/cold only.
- **`phases[].name`** follows the case flow: `opening → clarifying → structuring
  → analysis → math → synthesis` (use the subset the case needs).
- **`math_checkpoints[].inputs`** is an arithmetic expression over **literal
  numbers** (see §4). `common_errors[]` items are plain note strings naming
  known-wrong approaches — or `{value, note}` objects, where `value` is the
  numeric wrong result so the math checker can recognise it (T-023).
- **`exhibits[].unlock_condition`** — use `"phase:<name>"` to gate an exhibit on a
  phase (the phase must exist). Free-text intent conditions are allowed but not
  validated yet (full design is G-1 / T-016).
- **`curveballs[].trigger_phase`** and every `prerequisite_concepts` entry must
  resolve — the latter to an existing **lesson id**.
- **`rubric`** requires all five dimensions: `structure, math, judgment,
  communication, synthesis`, each with `anchors` (score → phrase). Anchor keys
  are the scores you want to illustrate (1, 3, 5 is enough).
- The **interviewer never sees** `model_answer`, `rubric`, `coaching`, `so_what`,
  or locked exhibits — that exclusion is enforced in code (07_PROMPTS §4), but it
  is why those fields are safe to write fully here.

### 3.4 `guesstimates/<id>.json`

```json
{
  "meta": {
    "id": "guess-petrol-pumps-delhi",
    "title": "Petrol pumps in Delhi",
    "difficulty": "easy",
    "est_minutes": 15,
    "region": "india",
    "diagnostic": true
  },
  "prompt": "Estimate the number of petrol pumps in Delhi.",
  "clarifications": [
    {"question_pattern": "only Delhi city", "answer": "Yes, NCT of Delhi only."}
  ],
  "approach": {
    "recommended": "top_down",
    "tree": [
      {"segment": "delhi_pop", "benchmark_refs": ["delhi_population"], "derivation": "delhi_population", "value": 2.0e7, "tolerance": 0.0},
      {"segment": "cars", "benchmark_refs": [], "derivation": "delhi_pop * 0.1", "value": 2.0e6, "tolerance": 1.0},
      {"segment": "pumps", "benchmark_refs": [], "derivation": "cars / 4000", "value": 500, "tolerance": 1.0}
    ]
  },
  "answer_range": {"low": 400, "high": 800},
  "common_traps": ["Forgetting that many households share one car."],
  "rubric": {
    "approach": {"anchors": {"1": "no method", "3": "picks one", "5": "justifies top-down"}},
    "segmentation": {"anchors": {"1": "none", "3": "coarse", "5": "clean segments"}},
    "arithmetic": {"anchors": {"1": "wrong", "3": "slow", "5": "fast"}},
    "sanity_check": {"anchors": {"1": "none", "3": "notices order", "5": "cross-checks"}}
  }
}
```

Key rules:

- **`approach.recommended`** is exactly `top_down` or `bottom_up`.
- **The tree is a computation, top to bottom.** Each `segment` has a `derivation`
  expression referencing **benchmark-ref keys** and/or **earlier segment names**.
  A literal `"given"` derivation means the `value` is an input, not recomputed.
- **The last segment is the final estimate** and must fall inside
  `answer_range` [low, high]. Write a final node that combines the rest.
- Every key in `benchmark_refs` must exist in `benchmarks.json`.
- **`rubric`** requires the four guesstimate dimensions: `approach, segmentation,
  arithmetic, sanity_check`.
- Flag diagnostic items with `"diagnostic": true` (2 of the seed 3; excluded from
  ladder recommendations but still browsable — G-9).

---

## 4. The six validation checks

Every file must pass all six (03_CONTENT_SPEC §4). A file that fails any check is
skipped, never partially loaded.

1. **Schema** — conforms to the pydantic model, including id patterns.
2. **Case math** — each `math_checkpoints[].inputs` is safely evaluated
   (arithmetic only: `+ - * / ** %`, parentheses, unary minus; **no names or
   function calls**) and must equal `expected_value` within `tolerance`.
3. **Guesstimate tree** — each non-`"given"` segment `value` is recomputed from
   its `derivation` (over benchmark refs + prior segments) within `tolerance`, and
   the final segment lands in `answer_range`.
4. **Benchmark refs** — every `benchmark_refs` key exists in `benchmarks.json`.
5. **References** — `prerequisite_concepts` are existing lesson ids;
   `curveball.trigger_phase` and `unlock_condition: "phase:X"` name existing
   phases; exhibit ids are unique within a case.
6. **Id uniqueness** — ids are unique across all four content types.

> **Float-tolerance gotcha.** A `tolerance: 0` checkpoint fails on floating-point
> results: `0.8 * 1 + 0.2 * 2` evaluates to `1.2000000000000002`, not `1.2`. Give
> any non-integer expected value a small tolerance (`0.001`); keep `0` only for
> exact-integer results.

### Running the validator

The CLI wrapper and pre-commit hook (T-012) are built. Validate every content
folder in one shot:

```sh
.venv/bin/python scripts/validate_case.py   # all four types; exits nonzero, lists each violation
```

Enable the hook once so validation + ruff run before every commit:

```sh
git config core.hooksPath .githooks
```

To validate a draft set programmatically (e.g. in a test), call the shared logic
directly:

```python
from app.engine.validation import validate_all
result = validate_all(benchmarks_raw, cases_raw, guesses_raw, lessons_raw)
for v in result.violations:
    print(v.file, v.check, v.detail)
```

---

## 5. Keeping this guide honest

If a schema field changes, update `app/engine/content_models.py` first, then this
guide and the fixtures under `tests/fixtures/content/valid/`. The models are the
contract; this document is a convenience that must not drift from them.
