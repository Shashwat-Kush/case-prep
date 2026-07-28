# Chaos check — Wi-Fi-kill degradation drill (T-071)

A semi-automated procedure that asserts CasePrep degrades gracefully when the
network drops mid-session. Router-level degradation is already covered by the
T-028 unit tests (mocked 429 + retry-after, retries-exhausted → next provider,
auth failure surfaced once then failover, offline flag → zero HTTP calls); this
drill confirms the **end-to-end user experience** on real hardware.

Run it at every phase gate tag from Phase 2 onward, and note the result in the
log at the bottom.

## Expected degradation (04_ENGINEERING_RULES §5, Degrade row)

| Surface | On network loss | Never |
|---------|-----------------|-------|
| **LLM chat** | Groq → Nvidia → Ollama failover; if all cloud is unreachable and an offline Ollama profile exists, it serves; otherwise a single clear error surfaces and the session stays open | A crash, a hang, or a silent empty reply |
| **STT** (voice) | Falls back to typed input; the mic shows the degrade state | Failing the whole turn |
| **TTS** (voice) | Text-only reply; audio simply omitted | Blocking the reply on audio |
| **Scoring** | Chunk fails visibly; the model-answer reveal is still shown | Losing the transcript |

The invariant: **a speech or provider failure never ends a session** — it drops
to the next-best modality.

## Procedure

1. **Baseline.** With Wi-Fi on, run `python scripts/chaos_check.py` — every cloud
   provider should read `UP`. Start a typed case and confirm streaming works.
2. **Kill the network.** Turn Wi-Fi off (or `sudo ifconfig en0 down`). Re-run
   `python scripts/chaos_check.py` — cloud providers should read `DOWN`; local
   Ollama reads `UP` only if it is running.
3. **Mid-turn drop (LLM).** Send a turn with Wi-Fi off. Expect either an Ollama
   reply (offline profile) or one clear "providers unavailable" message — the
   composer stays usable, no traceback in the browser or terminal.
4. **Voice degrade (STT).** Hold the mic and speak with Wi-Fi off. Expect the UI
   to fall back to typed input (transcript comes back empty/degraded), not an
   error dialog.
5. **Voice degrade (TTS).** If a reply is produced offline, confirm it renders as
   text with no audio, rather than hanging waiting for synthesis.
6. **Recover.** Turn Wi-Fi back on, re-run `python scripts/chaos_check.py`
   (providers `UP` again), send another turn, and confirm normal streaming
   resumes and the status indicator updates.

Abort criteria (a FAIL): any traceback reaching the user, a hung request with no
timeout, a session that cannot continue, or a keyed value printed anywhere.

## Result log

Note the gate tag, date, and PASS/FAIL. Keep the most recent entries.

| Gate tag | Date | Result | Notes |
|----------|------|--------|-------|
| _(e.g. phase-2-gate)_ | _YYYY-MM-DD_ | _PASS/FAIL_ | _observations_ |
