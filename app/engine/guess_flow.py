"""Coached guesstimate state machine (02_ARCHITECTURE §5, PRD Module J):
clarify -> approach -> segmentation -> estimation -> sanity_check.

Backend-owned (ADR-2): steps change only through explicit calls, so coached mode
pauses at each step. During estimation the flow walks the approach tree segment
by segment, capturing each user estimate as a structured number for scoring
(T-024). No expected values or the answer range are exposed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.content_models import Guesstimate, TreeSegment
from app.llm.templates import Message, build_guess_coach_context

STEPS = ["clarify", "approach", "segmentation", "estimation", "sanity_check"]
_SANITY = STEPS.index("sanity_check")


class GuessComplete(Exception):
    """Raised when advance() is called after the final step."""


class GuessFlowError(Exception):
    """Step misuse (e.g. advancing through estimation instead of estimating)."""


@dataclass(frozen=True)
class SegmentEstimate:
    segment: str
    value: float


class GuessFlow:
    def __init__(
        self,
        guess: Guesstimate,
        *,
        mode: str = "coached",
        transcript_window_turns: int = 12,
    ):
        if not guess.approach.tree:
            raise ValueError(f"guesstimate {guess.meta.id!r} has an empty tree")
        self._guess = guess
        self._mode = mode
        self._step_i = 0
        self._seg_i = 0
        self._estimates: list[SegmentEstimate] = []
        self._window = transcript_window_turns
        self._transcript: list[Message] = []

    @property
    def guess(self) -> Guesstimate:
        return self._guess

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def step(self) -> str:
        return STEPS[self._step_i] if self._step_i < len(STEPS) else "complete"

    @property
    def is_complete(self) -> bool:
        return self._step_i >= len(STEPS)

    @property
    def estimates(self) -> list[SegmentEstimate]:
        return list(self._estimates)

    # --- transitions (explicit only) ----------------------------------------

    def advance(self) -> str:
        """Move to the next step. Estimation is progressed with submit_estimate,
        not advance(); the flow leaves estimation once every segment is done."""
        if self.is_complete:
            raise GuessComplete(f"guesstimate {self._guess.meta.id!r} is complete")
        if self.step == "estimation":
            raise GuessFlowError(
                "use submit_estimate() to progress the estimation step"
            )
        self._step_i += 1
        return self.step

    # --- estimation ----------------------------------------------------------

    @property
    def current_segment(self) -> TreeSegment:
        self._require_estimation()
        return self._guess.approach.tree[self._seg_i]

    def submit_estimate(self, value: float) -> SegmentEstimate:
        """Capture the user's number for the current segment and move on. After
        the last segment the flow advances to sanity_check."""
        self._require_estimation()
        seg = self._guess.approach.tree[self._seg_i]
        est = SegmentEstimate(seg.segment, float(value))
        self._estimates.append(est)
        self._seg_i += 1
        if self._seg_i >= len(self._guess.approach.tree):
            self._step_i = _SANITY
        return est

    def _require_estimation(self) -> None:
        if self.step != "estimation":
            raise GuessFlowError(f"not in the estimation step (in {self.step!r})")

    # --- transcript / context ------------------------------------------------

    def record_turn(self, role: str, content: str) -> None:
        self._transcript.append({"role": role, "content": content})

    def transcript_window(self) -> list[Message]:
        return self._transcript[-self._window :] if self._window > 0 else []

    def context(
        self, *, stage_facts: str = "", math_verdicts: str = ""
    ) -> list[Message]:
        segment = self.current_segment.segment if self.step == "estimation" else None
        return build_guess_coach_context(
            self._guess,
            step=self.step,
            segment=segment,
            transcript=self.transcript_window(),
            stage_facts=stage_facts,
            math_verdicts=math_verdicts,
        )
