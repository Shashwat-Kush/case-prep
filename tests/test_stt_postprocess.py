"""STT number cleanup + confirmation gate (T-052). Spoken numbers are error-prone,
so every stated number is surfaced for confirmation and only confirmed numbers may
reach the math checker."""

from app.engine.content_models import CommonError, MathCheckpoint
from app.engine.stt_postprocess import (
    clean_transcript,
    detect_numbers,
    evaluate_confirmed,
)


def _cp(expected, tol=0.0, errors=()):
    return MathCheckpoint(
        inputs="x",
        expected_value=expected,
        tolerance=tol,
        common_errors=list(errors),
    )


def _one(text):
    nums = detect_numbers(text)
    assert len(nums) == 1, nums
    return nums[0]


# --- cleanup / detection cases ----------------------------------------------


def test_teen_ty_ambiguity_offers_both_readings():
    n = _one("we sold fifteen crore units")
    assert n.value == 15 * 1e7
    assert n.candidates == [15 * 1e7, 50 * 1e7]  # fifteen vs fifty


def test_thirteen_thirty_is_also_confusable():
    assert _one("thirty").candidates == [30, 13]


def test_lakh_and_crore_scale_words():
    assert _one("fifty lakh").value == 50 * 1e5
    assert _one("two crore").value == 2 * 1e7


def test_mixed_digit_and_scale_word():
    n = _one("about 2.5 crore rupees")  # currency dropped, digit + scale
    assert n.value == 2.5 * 1e7
    assert n.candidates == [2.5 * 1e7]  # digits are not teen/ty confusable


def test_currency_is_stripped():
    assert _one("₹500").value == 500
    assert _one("Rs. 1,50,000").value == 150000  # Indian grouping


def test_percent_and_hundred_composition():
    assert _one("twenty percent").value == 0.2
    assert _one("two hundred").value == 200


def test_clean_transcript_collapses_numbers_to_digits():
    assert clean_transcript("we sold fifteen crore up from ₹500") == (
        "we sold 150000000 up from 500"
    )


def test_multiple_numbers_detected_in_order():
    vals = [n.value for n in detect_numbers("ten and 20 and thirty")]
    assert vals == [10, 20, 30]


# --- confirmation gate ------------------------------------------------------


def test_unconfirmed_number_never_reaches_checkpoint():
    # The transcript literally contains 500 (the expected value), but nothing is
    # evaluated until the user confirms — the gate takes only confirmed numbers.
    cp = _cp(500)
    assert evaluate_confirmed(cp, []).matched_expected is False


def test_confirmed_number_is_evaluated():
    cp = _cp(500)
    assert evaluate_confirmed(cp, [500]).matched_expected is True


def test_confirming_the_corrected_reading_matches():
    # Heard "fifteen crore" but the truth was "fifty crore"; confirming the
    # alternate candidate is what the checkpoint sees.
    n = _one("fifteen crore")
    cp = _cp(50 * 1e7)
    assert evaluate_confirmed(cp, [n.candidates[1]]).matched_expected is True


def test_common_error_still_flagged_on_confirmed_number():
    cp = _cp(100, errors=[CommonError(value=80, note="forgot the tax")])
    res = evaluate_confirmed(cp, [80])
    assert res.matched_expected is False and res.common_error == "forgot the tax"
