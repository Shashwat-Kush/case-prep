# decisions.md

Implementation-time decisions, verified provider limits, and deviations from the
handbook (04_ENGINEERING_RULES §10). Newest first.

## 2026-07-27 · Environment: broken venv pip workaround

On this machine, `python3.12 -m venv` bundles a pip whose vendored `packaging`
uses possessive-quantifier regex that this interpreter's `re` mis-evaluates, so
`Version("0.dev0")` raises `InvalidVersion` and every venv-local pip command
fails. The **base** interpreter's older pip (23.1.2) works.

Workaround used to populate `.venv`:

```sh
python3.12 -m venv .venv
/usr/local/bin/python3.12 -m pip install --target .venv/lib/python3.12/site-packages -r requirements.txt
```

Standing action item: fix the base install (`pip3.12 install --upgrade pip` from a
shell where it works, or reinstall python.org 3.12) so the README's plain
`pip install -r requirements.txt` works. Not code-blocking.

## 2026-07-27 · Math-checkpoint recompute form (T-010, resolves an unlisted gap)

03_CONTENT_SPEC §4.2 requires "recompute every case `math_checkpoint` from its
`inputs`", but §2.1 lists no formula field. Resolution (minimal, no new schema
field): `inputs` is an **arithmetic expression string over literal numbers**
(e.g. `"(1500 - 1200) / 1500"`). The validator/math checker safely evaluates it
(ast, arithmetic only — no names/calls) and compares to `expected_value` within
`tolerance`. `common_errors[]` are `{value, note}`: known-wrong results matched
within tolerance to give targeted feedback (T-023). Guesstimate `tree[].derivation`
follows the same rule but may also reference `benchmark_refs` keys and prior
segment names (settled at T-011).

## 2026-07-27 · Validator recompute/reference conventions (T-011)

Filling gaps in 03_CONTENT_SPEC §4 checks 3 and 5, minimally:

- **Guesstimate tree (check 3):** each `tree[].derivation` is an arithmetic
  expression over benchmark-ref keys and *prior* segment names, evaluated safely
  (ast). A literal `"given"` derivation means the `value` is an input, not
  recomputed. The **final segment's value is the estimate**; it must fall within
  `answer_range` [low, high]. Authors write a final node that combines the rest.
- **Exhibit reference (check 5):** an `unlock_condition` of the form
  `phase:<name>` must name an existing phase (dangling-exhibit check). Other
  unlock_condition text is free intent, unchecked here — the full runtime unlock
  design is G-1, settled at T-016. `curveball.trigger_phase` must also name an
  existing phase; exhibit ids must be unique within a case.
- **Lesson reference (check 5):** `case.meta.prerequisite_concepts` entries must
  be existing lesson **ids** (per §4.5, which overrides the §2.3 note that reads
  them as concept labels).

## Provider limits

Phase 0 step 5: record verified Groq/Nvidia free-tier limits here with the date
once accounts are set up (T-003). Docs elsewhere cite indicative numbers only.

## MathCheckpoint.common_errors shape (T-013)

Relaxed `common_errors` from `list[{value, note}]` to `list[str]` (plain note
strings). Rationale: nothing reads the numeric `value` — the validator and engine
only ever surface the note text — and seed authors naturally wrote notes-only.
Keeping the numeric field forced fabricated wrong-answer values with no consumer.
YAGNI. If a future feature needs to match a candidate's wrong number to a named
error, reintroduce a structured form then.

## Number parsing spec (G-4, settled for T-023)

The math checker parses numbers from free-text user turns as follows:

- **Integers / decimals:** `80`, `0.2`, `-5`, `12.5`.
- **Grouping:** commas are stripped before conversion, so both Western
  (`1,500`, `150,000`) and Indian (`1,50,000`) groupings parse to the same value.
- **Scale suffixes** (case-insensitive, optional space): `%` (×0.01),
  `k`/`thousand` (×1e3), `lakh`/`lakhs`/`lac` (×1e5), `million`/`millions`/`mn`
  (×1e6), `crore`/`crores`/`cr` (×1e7), `billion`/`billions`/`bn` (×1e9).
  Bare single letters `m`/`b` are intentionally NOT scale suffixes (too many
  false positives); use `mn`/`bn`.
- **Currency** (`Rs`, `Rs.`, `INR`, `₹`, `$`) is stripped and ignored.
- An unknown trailing word after a number is ignored (the number still parses).
- All numeric tokens in a turn are extracted, in order.

## common_errors is hybrid (revisits the T-013 relaxation, for T-023)

Each `common_errors` item may be a plain note string OR a `{value, note}` object.
The math checker numerically matches only items that carry a `value`; string-only
items remain valid content (seed authoring style) but are not numerically
matched. This keeps the YAGNI relaxation for authors while letting a checkpoint
opt into known-wrong-value detection.
