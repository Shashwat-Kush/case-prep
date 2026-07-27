# Web UI manual checklist (T-041+)

Automated tests cover the HTTP/SSE contract and full-flow completion at the API
level (`tests/test_web.py`, `tests/test_web_live.py`). The browser UI itself is
verified by hand. Run the server and walk this list:

```sh
python -m app.main        # binds 127.0.0.1:8000 (config.host/port)
# open http://127.0.0.1:8000
```

## Library

- [ ] Cases, Lessons, and Guesstimates each list their content from the loader.
- [ ] Cases show a standard/guided selector; guesstimates a coached/timed selector.
- [ ] Clicking an item starts a session; `← library` returns without reload.

## Guided case (completable)

- [ ] Prompt and phase show; coach explanation appears on phases that have one.
- [ ] "Reveal approach" before answering is refused ("…before the candidate has
      attempted").
- [ ] After typing an answer (streamed reply appears token-by-token), reveal shows
      the model approach.
- [ ] "Next phase" walks all phases; "Finish" ends and shows the model answer.
- [ ] Exhibit buttons appear only once the exhibit is unlocked (auto on its phase,
      or via an intent unlock); clicking one renders its data as a table.
- [ ] A live timer shows on each phase; on a phase with a budget it counts against
      it and turns red past the budget. Overrunning a phase then finishing lists
      the overrun phases in the end-of-case pacing note.

## Lesson (completable)

- [ ] Sections render; "Next" walks them; Q&A during a section streams a reply.
- [ ] Quiz options render as buttons; picking one shows correct/incorrect +
      explanation.
- [ ] After the last question, coverage (quiz score + concepts) shows.

## Coached guesstimate (completable)

- [ ] Prompt and step show; "Next step" advances clarify → approach → segmentation.
- [ ] In estimation, a number input appears per segment; "Submit estimate" advances.
- [ ] Each submitted estimate shows an inline verdict in the transcript (✓ in the
      ballpark, or ✗ too high/too low) — coached mode only; timed mode shows none.
- [ ] After the last segment, remaining steps advance to a completion summary
      listing every estimate, plus a final range check (✓/✗ vs. the answer range).

## Session review (T-046)

- [ ] After finishing a case, "Review session" opens a scorecard (per-dimension
      score + average) above the full transcript.
- [ ] Each evidence quote is clickable and scrolls to + briefly highlights the
      transcript turn it was lifted from; unmatched quotes are shown disabled.

## Provider status (T-044)

- [ ] The header shows the live provider and remaining request headroom, refreshing
      periodically and after each turn.
- [ ] Forcing a failover (e.g. bad primary key) flips the indicator to the fallback
      provider and highlights it.

## Push-to-talk (T-050)

- [ ] Holding 🎤 turns it red and records; the browser asks for mic permission
      the first time. Releasing uploads the clip.
- [ ] A released clip is transcribed (T-051) and drops into the input for you to
      review/edit before sending; on STT failure a "couldn't transcribe — type"
      note shows and typing still works exactly as before (degrade-to-typed).
- [ ] Any spoken number is number-cleaned (fifteen → 15, lakh/crore scaled,
      currency dropped) and listed under the composer for confirmation (T-052);
      teen/ty homophones (fifteen/fifty) offer the alternate as a one-click fix,
      and every number is editable before you Send.
- [ ] Denying mic permission shows a prompt to type instead, without breaking the
      session.

## Cross-cutting

- [ ] Typed input always available where chat applies (composer hidden only in
      quiz / estimation / completion where free text does not apply).
- [ ] Server bound to localhost only (no external interface reachable).
