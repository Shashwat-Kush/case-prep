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

## Lesson (completable)

- [ ] Sections render; "Next" walks them; Q&A during a section streams a reply.
- [ ] Quiz options render as buttons; picking one shows correct/incorrect +
      explanation.
- [ ] After the last question, coverage (quiz score + concepts) shows.

## Coached guesstimate (completable)

- [ ] Prompt and step show; "Next step" advances clarify → approach → segmentation.
- [ ] In estimation, a number input appears per segment; "Submit estimate" advances.
- [ ] After the last segment, remaining steps advance to a completion summary
      listing every estimate.

## Cross-cutting

- [ ] Typed input always available where chat applies (composer hidden only in
      quiz / estimation / completion where free text does not apply).
- [ ] Server bound to localhost only (no external interface reachable).
