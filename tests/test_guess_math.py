import json
from pathlib import Path

from app.engine.content_models import Guesstimate
from app.engine.guess_flow import SegmentEstimate
from app.engine.math_checker import check_estimates, check_final

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "content"
    / "valid"
    / "guesstimates"
    / "guess-petrol-pumps-delhi.json"
)


def _guess() -> Guesstimate:
    return Guesstimate.model_validate(json.loads(FIXTURE.read_text()))


# tree: delhi_pop=2e7 (tol 0), cars=2e6 (tol 1.0), pumps=500 (tol 1.0); range [400,800]


def test_all_segments_correct_and_final_in_range():
    ests = [
        SegmentEstimate("delhi_pop", 2.0e7),
        SegmentEstimate("cars", 2.0e6),
        SegmentEstimate("pumps", 500),
    ]
    checks = check_estimates(_guess(), ests)
    assert all(c.ok for c in checks)
    assert check_final(_guess(), 500).in_range is True


def test_relative_tolerance_allows_factor_of_two():
    # cars expected 2e6 with tolerance 1.0 -> band is +/-100%
    within = check_estimates(_guess(), [SegmentEstimate("cars", 3.5e6)])[0]
    outside = check_estimates(_guess(), [SegmentEstimate("cars", 4.5e6)])[0]
    assert within.ok is True
    assert outside.ok is False


def test_planted_wrong_step_flagged():
    ests = [
        SegmentEstimate("delhi_pop", 2.0e7),
        SegmentEstimate("cars", 9.9e6),  # planted wrong
        SegmentEstimate("pumps", 500),
    ]
    checks = check_estimates(_guess(), ests)
    bad = [c for c in checks if not c.ok]
    assert [c.segment for c in bad] == ["cars"]
    assert bad[0].expected == 2.0e6


def test_benchmark_pinned_segment_needs_exact():
    # delhi_pop has tolerance 0 -> must match closely
    off = check_estimates(_guess(), [SegmentEstimate("delhi_pop", 3.0e7)])[0]
    assert off.ok is False


def test_final_out_of_range():
    assert check_final(_guess(), 5).in_range is False
    assert check_final(_guess(), 5000).in_range is False
