# decisions.md

Implementation-time decisions, verified provider limits, and deviations from the
handbook (04_ENGINEERING_RULES §10). Newest first.

## 2026-07-28 · G-2 settled: plain HTML/JS + SSE transport (T-040)

Frontend is plain HTML/JS (no framework, no build step); streaming transport is
**Server-Sent Events** over plain HTTP. The case loop is one-directional (browser
POSTs a turn → server streams reply tokens), so SSE fits exactly and avoids
WebSocket bidirectionality. The browser holds only an opaque `session_id`; all
case state lives server-side in the engine (ADR-2). API: `POST /api/session`
(create), `POST /api/session/{sid}/message` (SSE token stream), `POST
/api/session/{sid}/advance` (phase → terminal reveal). `create_app(engine)` takes
the engine as a seam so route contracts test against a fake. Revisit the framework
choice only if the dashboard (T-062) needs components.

Side effect: `Store` now opens sqlite with `check_same_thread=False` — FastAPI
runs sync endpoints in a worker thread, so the single-user connection must cross
threads. Safe because access is sequential (one user).

## 2026-07-28 · Router failover: lazy-stream priming + taxonomy mapping (T-028)

The chat stream is lazy — HTTP status and connection errors surface only on the
first token, not at `stream()`. So the router **primes** each provider (pulls one
token inside its own generator) to classify the outcome before committing, then
re-yields that token. This keeps streaming intact while making failover
transparent to callers.

Taxonomy → HTTP mapping (04 §5), decided where the handbook left the status
codes implicit:
- **Retryable:** `429` (honor `retry-after` exactly when present, else
  exponential backoff `base·2^attempt` + jitter; max `retry.max_retries`), `5xx`,
  and any non-connect `httpx.HTTPError` (timeouts / transient network).
- **Failover:** `httpx.ConnectError` (connection refused) → next provider with no
  backoff; also retries-exhausted falls through to the next provider.
- **Fatal-for-turn:** `401/403` (auth) is surfaced **once per session** (per
  provider) then fails over; `400` and other 4xx (invalid request) raise
  `RouterError` with **no** failover — the same request fails everywhere.

**Daily-cap** isn't distinguished from a normal `429` (would require parsing
provider-specific bodies, YAGNI): it retries then naturally fails over when
exhausted. **Offline** restricts the chain to keyless (local) providers, so cloud
is never constructed or called. The router instance is the session, so the
"surface auth once per session" state lives on it.

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

## Guesstimate segment tolerance is relative (T-024)

When judging a user's segment estimate against the tree's expected value, the
segment `tolerance` is treated as a RELATIVE fraction of the expected value
(band = |tolerance * expected|), because guesstimates are order-of-magnitude:
tolerance 0 means "state it exactly" (benchmark-pinned segments), 1.0 means
"within a factor of two". This differs from content validation (T-011), where
derivations recompute exactly so the absolute check is immaterial in practice.
The final answer is checked against answer_range [low, high].

## KNOWN ISSUE (deferred, found in live testing 2026-07-28): guesstimate tolerances authored as absolute

Every seeded and converted guesstimate authored `tree[].tolerance` as an
ABSOLUTE number (e.g. households `tolerance: 1000000`), but the live coached
checker treats it as RELATIVE: `check_segment` computes
`band = abs(tolerance * expected)` (`app/engine/math_checker.py:108`). So a
segment expecting 7,500,000 with tolerance 1,000,000 gets a band of
1,000,000 × 7,500,000 ≈ 7.5e12, accepting any estimate — the coached per-step
"too high / too low" direction hint never fires. Confirmed live: a 20,000,000
estimate against a 7,500,000 expected returned `ok: True`.

Impact is limited to coached-mode directional feedback; the final-answer
`answer_range` check (the real correctness gate) and content validation are
unaffected (derivations recompute exactly, so `abs(0) <= any tolerance` passes).

Fix when picked up: reset each guesstimate segment `tolerance` to a small
relative fraction (~0.2–0.3; tighter/0 for benchmark-pinned segments) across all
17 files in `guesstimates/`. Validation stays green. Not changing now, per user.

## Spoken-number confirmation gate (T-052)

Spoken numbers are unreliable (teen/ty homophones — fifteen/fifty, thirteen/
thirty — plus lakh/crore mixed with digits), so no number from STT may reach the
math checker until the user confirms it. `app/engine/stt_postprocess.py`:

- `detect_numbers(text)` parses each stated number — words, digits, Indian scale
  words, `%`, and `hundred` composition — and, when the phrase contains exactly
  one teen/ty homophone, offers the swapped reading as a second candidate.
- `clean_transcript(text)` collapses each number phrase to its primary digit
  value for display (punctuation between tokens is dropped).
- `evaluate_confirmed(cp, values)` is the ONLY path from a spoken turn to a
  checkpoint: it calls `math_checker.check_values` on user-confirmed numbers.
  `check_checkpoint(cp, text)` (free-text) also routes through `check_values`,
  keeping one comparison core. Detected-but-unconfirmed numbers are never
  evaluated, so a misheard number cannot silently fail a checkpoint.
