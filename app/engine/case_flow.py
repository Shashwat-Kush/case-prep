"""Case state machine (02_ARCHITECTURE §5). Backend-owned (ADR-2): phases only
change through an explicit advance() call — the LLM never drives transitions.

Each per-call context carries only the current phase's instructions plus the
recent transcript window (07_PROMPTS §3); the exclusion rules ride along from
app.llm.templates. Exhibits with a `phase:<name>` unlock condition open on entry
to that phase; intent-based ("candidate asks…") ones open via unlock_exhibit(),
the engine's judgment call (G-1 full design later).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.engine.content_models import Case, Phase
from app.llm.templates import (
    Message,
    build_coach_context,
    build_interviewer_context,
)


class CaseComplete(Exception):
    """Raised when advance() is called at the final phase."""


class CoachError(Exception):
    """Coach-step misuse: not in guided mode, no coaching this phase, or a
    reveal requested before the candidate has attempted (T-018)."""


class CaseFlow:
    def __init__(
        self,
        case: Case,
        *,
        mode: str = "standard",
        transcript_window_turns: int = 12,
        now: Callable[[], float] = time.monotonic,
    ):
        if not case.phases:
            raise ValueError(f"case {case.meta.id!r} has no phases")
        if mode == "guided" and not any(p.coaching for p in case.phases):
            raise ValueError(
                f"case {case.meta.id!r} has no coaching blocks; guided mode unavailable"
            )
        self._case = case
        self._mode = mode
        self._i = 0
        self._window = transcript_window_turns
        self._transcript: list[Message] = []
        self._exhibit_ids = {e.id for e in case.exhibits}
        self._unlocked: set[str] = set()
        self._attempted = False
        self._now = now
        self._phase_started = now()
        self._timings: list[dict] = []
        self._auto_unlock()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def case(self) -> Case:
        return self._case

    @property
    def current_phase(self) -> Phase:
        return self._case.phases[self._i]

    @property
    def phase_name(self) -> str:
        return self.current_phase.name

    @property
    def is_terminal(self) -> bool:
        return self._i >= len(self._case.phases) - 1

    @property
    def unlocked_exhibit_ids(self) -> frozenset[str]:
        return frozenset(self._unlocked)

    # --- pacing (T-043) ------------------------------------------------------

    @property
    def phase_budget_s(self) -> float | None:
        """The current phase's time budget in seconds (time_budget is minutes)."""
        b = self.current_phase.time_budget
        return b * 60 if b else None

    def close(self) -> None:
        """Capture timing for the final phase when the case ends (advance() does
        this for every earlier phase)."""
        self._close_phase()

    def _close_phase(self) -> None:
        budget_s = self.phase_budget_s
        elapsed = self._now() - self._phase_started
        self._timings.append(
            {
                "phase": self.phase_name,
                "budget_s": budget_s,
                "elapsed_s": elapsed,
                "over": budget_s is not None and elapsed > budget_s,
            }
        )

    @property
    def timings(self) -> list[dict]:
        return list(self._timings)

    @property
    def overruns(self) -> list[dict]:
        return [t for t in self._timings if t["over"]]

    # --- transitions (explicit only) ----------------------------------------

    def advance(self) -> Phase:
        if self.is_terminal:
            raise CaseComplete(f"case {self._case.meta.id!r} is at its final phase")
        self._close_phase()  # capture timing for the phase being left
        self._i += 1
        self._attempted = False  # a fresh attempt is required in each phase
        self._phase_started = self._now()
        self._auto_unlock()
        return self.current_phase

    def _auto_unlock(self) -> None:
        target = f"phase:{self.phase_name}"
        for e in self._case.exhibits:
            if e.unlock_condition.strip() == target:
                self._unlocked.add(e.id)

    # --- exhibits ------------------------------------------------------------

    def unlock_exhibit(self, exhibit_id: str) -> None:
        if exhibit_id not in self._exhibit_ids:
            raise KeyError(f"no exhibit {exhibit_id!r} in case {self._case.meta.id!r}")
        self._unlocked.add(exhibit_id)

    def is_unlocked(self, exhibit_id: str) -> bool:
        return exhibit_id in self._unlocked

    # --- transcript ----------------------------------------------------------

    def record_turn(self, role: str, content: str) -> None:
        if role == "user":
            self._attempted = True  # the candidate's turn is their attempt
        self._transcript.append({"role": role, "content": content})

    # --- guided coach step (T-018) -------------------------------------------

    @property
    def has_coaching(self) -> bool:
        return self.current_phase.coaching is not None

    @property
    def attempted(self) -> bool:
        return self._attempted

    def coach_explain(self) -> str:
        """What a strong candidate does this phase — verbatim from the file."""
        coaching = self._coaching()
        return coaching.explain

    def coach_reveal(self) -> str:
        """The model approach for this phase — verbatim, only after an attempt."""
        coaching = self._coaching()
        if not self._attempted:
            raise CoachError(
                f"cannot reveal the model approach for {self.phase_name!r} "
                "before the candidate has attempted"
            )
        return coaching.model_approach_for_phase

    def _coaching(self):
        if self._mode != "guided":
            raise CoachError(f"coach steps require guided mode, in {self._mode!r}")
        coaching = self.current_phase.coaching
        if coaching is None:
            raise CoachError(f"phase {self.phase_name!r} has no coaching block")
        return coaching

    def transcript_window(self) -> list[Message]:
        return self._transcript[-self._window :] if self._window > 0 else []

    @property
    def transcript(self) -> list[Message]:
        """The full transcript (scoring trims it to its own budget, T-025)."""
        return list(self._transcript)

    # --- per-call context ----------------------------------------------------

    def context(
        self,
        persona: str = "interviewer",
        *,
        stage_facts: str | None = None,
        math_verdicts: str = "",
        pushback_intensity: str = "gentle",
    ) -> list[Message]:
        """Assemble the LLM context for the current phase: current-phase
        instructions + unlocked exhibits + the recent transcript window only."""
        facts = self._stage_facts() if stage_facts is None else stage_facts
        ids = sorted(self._unlocked)
        window = self.transcript_window()
        if persona == "coach":
            reveal = self._attempted if self._mode == "guided" else True
            return build_coach_context(
                self._case,
                phase_name=self.phase_name,
                unlocked_exhibit_ids=ids,
                transcript=window,
                stage_facts=facts,
                math_verdicts=math_verdicts,
                reveal_model_approach=reveal,
            )
        if persona == "interviewer":
            return build_interviewer_context(
                self._case,
                phase_name=self.phase_name,
                unlocked_exhibit_ids=ids,
                transcript=window,
                stage_facts=facts,
                math_verdicts=math_verdicts,
                pushback_intensity=pushback_intensity,
            )
        raise ValueError(f"unsupported persona for a case: {persona!r}")

    def _stage_facts(self) -> str:
        p = self.current_phase
        facts = f"Phase {self._i + 1} of {len(self._case.phases)}: {p.name}."
        if p.time_budget:
            facts += f" Suggested time: {p.time_budget} min."
        return facts
