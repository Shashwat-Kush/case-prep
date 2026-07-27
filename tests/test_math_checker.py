import pytest

from app.engine.content_models import MathCheckpoint
from app.engine.math_checker import check_checkpoint, parse_numbers


@pytest.mark.parametrize(
    "text,expected",
    [
        ("80", [80.0]),
        ("1,500", [1500.0]),
        ("1,50,000", [150000.0]),  # Indian grouping
        ("150,000", [150000.0]),  # Western grouping
        ("0.2", [0.2]),
        ("-5", [-5.0]),
        ("20%", [0.2]),
        ("3 crore", [3e7]),
        ("1.5 cr", [1.5e7]),
        ("75 lakh", [7.5e6]),
        ("2 million", [2e6]),
        ("4 bn", [4e9]),
        ("Rs 1,200", [1200.0]),
        ("₹2.5 crore", [2.5e7]),
        ("profit 300 at 20% margin", [300.0, 0.2]),
        ("about 40 stores", [40.0]),  # unknown trailing word ignored
        ("no numbers here", []),
    ],
)
def test_parse_numbers(text, expected):
    assert parse_numbers(text) == pytest.approx(expected)


def _cp(expected, tol=0.0, common_errors=None):
    return MathCheckpoint.model_validate(
        {
            "inputs": "0",
            "expected_value": expected,
            "tolerance": tol,
            "common_errors": common_errors or [],
        }
    )


def test_correct_answer_matches():
    r = check_checkpoint(_cp(0.2, 0.001), "the margin is 20%")
    assert r.matched_expected is True
    assert r.matched_value == pytest.approx(0.2)
    assert r.common_error is None


def test_incorrect_answer_no_match():
    r = check_checkpoint(_cp(0.2, 0.001), "I think it's 50%")
    assert r.matched_expected is False
    assert r.common_error is None


def test_tolerance_edge():
    within = check_checkpoint(_cp(0.2, 0.001), "0.2005")
    outside = check_checkpoint(_cp(0.2, 0.001), "0.25")
    assert within.matched_expected is True
    assert outside.matched_expected is False


def test_common_error_identified_by_value():
    cp = _cp(0.2, 0.001, common_errors=[{"value": 0.25, "note": "divided by cost"}])
    r = check_checkpoint(cp, "it's 25%")
    assert r.matched_expected is False
    assert r.common_error == "divided by cost"


def test_string_common_error_not_numerically_matched():
    cp = _cp(0.2, 0.001, common_errors=["divided by cost instead of revenue"])
    r = check_checkpoint(cp, "it's 25%")  # 0.25, but the note carries no value
    assert cp.common_errors[0].value is None
    assert cp.common_errors[0].note == "divided by cost instead of revenue"
    assert r.common_error is None


def test_expected_wins_over_common_error():
    cp = _cp(0.2, 0.001, common_errors=[{"value": 0.25, "note": "wrong"}])
    r = check_checkpoint(cp, "could be 25% but I'll say 20%")
    assert r.matched_expected is True  # correct value present -> reported correct
    assert r.common_error is None
