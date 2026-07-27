import copy
import json
from pathlib import Path

import pytest

from app.engine.validation import safe_eval, validate_all

FIXTURES = Path(__file__).parent / "fixtures" / "content" / "valid"


def _load():
    benchmarks = (
        str(FIXTURES / "benchmarks.json"),
        json.loads((FIXTURES / "benchmarks.json").read_text()),
    )
    cases = [
        (str(p), json.loads(p.read_text())) for p in (FIXTURES / "cases").glob("*.json")
    ]
    guesses = [
        (str(p), json.loads(p.read_text()))
        for p in (FIXTURES / "guesstimates").glob("*.json")
    ]
    lessons = [
        (str(p), json.loads(p.read_text()))
        for p in (FIXTURES / "lessons").glob("*.json")
    ]
    return benchmarks, cases, guesses, lessons


def test_valid_set_has_no_violations():
    result = validate_all(*_load())
    assert result.violations == []
    assert "case-cement-profitability" in {c.meta.id for c in result.cases.values()}
    assert "guess-petrol-pumps-delhi" in {
        g.meta.id for g in result.guesstimates.values()
    }


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("(1500 - 1200) / 1500", 0.2),
        ("2 ** 3", 8.0),
        ("-5 + 10", 5.0),
        ("100 / 4000", 0.025),
    ],
)
def test_safe_eval_arithmetic(expr, expected):
    assert safe_eval(expr, {}) == pytest.approx(expected)


def test_safe_eval_rejects_calls():
    from app.engine.validation import MathExprError

    with pytest.raises(MathExprError):
        safe_eval("__import__('os').system('x')", {})


def _checks(violations, check):
    return [v for v in violations if v.check == check]


def test_bad_schema():
    b, cases, g, lessons = _load()
    cases[0][1]["prompt"] = 123  # wrong type
    v = validate_all(b, cases, g, lessons).violations
    assert _checks(v, "schema")


def test_wrong_checkpoint():
    b, cases, g, lessons = _load()
    cases[0][1]["math_checkpoints"][0]["expected_value"] = 0.99
    v = validate_all(b, cases, g, lessons).violations
    assert _checks(v, "math_checkpoint")


def test_broken_tree():
    b, cases, g, lessons = _load()
    g[0][1]["approach"]["tree"][1]["value"] = 999  # derivation no longer matches
    v = validate_all(b, cases, g, lessons).violations
    assert _checks(v, "guesstimate_tree")


def test_final_estimate_out_of_range():
    b, cases, g, lessons = _load()
    g[0][1]["answer_range"] = {"low": 1, "high": 10}
    v = validate_all(b, cases, g, lessons).violations
    assert any("answer_range" in x.detail for x in _checks(v, "guesstimate_tree"))


def test_missing_benchmark_ref():
    b, cases, g, lessons = _load()
    g[0][1]["approach"]["tree"][0]["benchmark_refs"] = ["nonexistent_benchmark"]
    v = validate_all(b, cases, g, lessons).violations
    assert _checks(v, "benchmark_ref")


def test_dangling_lesson_ref():
    b, cases, g, lessons = _load()
    cases[0][1]["meta"]["prerequisite_concepts"] = ["lesson-does-not-exist"]
    v = validate_all(b, cases, g, lessons).violations
    assert _checks(v, "reference")


def test_dangling_exhibit_phase_ref():
    b, cases, g, lessons = _load()
    cases[0][1]["exhibits"][0]["unlock_condition"] = "phase:ghost"
    v = validate_all(b, cases, g, lessons).violations
    assert any("unknown phase" in x.detail for x in _checks(v, "reference"))


def test_duplicate_id():
    b, cases, g, lessons = _load()
    dup = copy.deepcopy(cases[0])
    cases.append((str(FIXTURES / "cases" / "case-copy.json"), dup[1]))
    result = validate_all(b, cases, g, lessons)
    assert _checks(result.violations, "duplicate_id")
    assert "case-cement-profitability" not in {c.meta.id for c in result.cases.values()}
