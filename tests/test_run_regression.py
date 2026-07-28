"""Prompt-regression violation detectors (T-070). The live run is network and
eyeballed by hand; here we test each pure detector against canned bad outputs and
confirm the canned-input files hold 10-15 lines per persona (07_PROMPTS §6)."""

from scripts.run_regression import (
    PERSONAS,
    bad_scoring_json,
    broken_character,
    coach_reveal_before_attempt,
    invented_numbers,
    leaked_solution,
    load_inputs,
)


def test_broken_character_flags_meta_commentary():
    v = broken_character("As an AI language model, I cannot pretend to interview.")
    kinds = {x.kind for x in v}
    assert kinds == {"broken-character"}
    assert len(v) >= 1


def test_broken_character_flags_markdown_headers():
    assert broken_character("# Structure\nLet's begin.")
    assert not broken_character("Let's begin. Walk me through your approach.")


def test_invented_numbers_flags_only_numbers_absent_from_slice():
    slice_ = "Revenue is 500 and cost is 300."
    out = "Revenue 500, cost 300, but margin is 40 percent and profit 200."
    flagged = {v.detail for v in invented_numbers(out, slice_)}
    assert flagged == {"40", "200"}  # 500 and 300 are in the slice, allowed


def test_invented_numbers_ignores_comma_grouping():
    assert invented_numbers("about 1,000 units", "we sold 1000 units") == []


def test_leaked_solution_matches_forbidden_phrases():
    forbidden = ["cut the underperforming plant", "raise prices by ten percent"]
    out = "You should cut the underperforming plant to fix margins."
    v = leaked_solution(out, forbidden)
    assert len(v) == 1 and v[0].kind == "leaked-solution"


def test_leaked_solution_clean_when_no_phrase_present():
    assert leaked_solution("What drives the cost side?", ["cut the plant"]) == []


def test_coach_reveal_before_attempt_detects_verbatim_leak():
    approach = "Segment revenue by product line, then isolate the declining segment."
    assert coach_reveal_before_attempt(approach, approach)  # full leak
    assert not coach_reveal_before_attempt("What's your first bucket?", approach)


def test_bad_scoring_json_flags_non_json():
    assert bad_scoring_json("here are the scores: 4/5")
    assert bad_scoring_json('{"scores": {}}') == []


def test_each_persona_has_10_to_15_canned_inputs():
    for persona in PERSONAS:
        n = len(load_inputs(persona))
        assert 10 <= n <= 15, f"{persona} has {n} inputs"
