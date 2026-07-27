"""Case state machine (02_ARCHITECTURE §5). Backend-owned (ADR-2): phases only
change through an explicit advance() call — the LLM never drives transitions.

Each per-call context carries only the current phase's instructions plus the
recent transcript window (07_PROMPTS §3); the exclusion rules ride along from
app.llm.templates. Exhibits with a `phase:<name>` unlock condition open on entry
to that phase; intent-based ("candidate asks…") ones open via unlock_exhibit(),
the engine's judgment call (G-1 full design later).
"""

from __future__ import annotations

from app.engine.content_models import Case, Phase
from app.llm.templates import (
    Message,
    build_coach_context,
    build_interviewer_context,
)


class CaseComplete(Exception):
    """Raised when advance() is called at the final phase."""


class CaseFlow:
    def __init__(self, case: Case, *, transcript_window_turns: int = 12):
        if not case.phases:
            raise ValueError(f"case {case.meta.id!r} has no phases")
        self._case = case
        self._i = 0
        self._window = transcript_window_turns
        self._transcript: list[Message] = []
        self._exhibit_ids = {e.id for e in case.exhibits}
        self._unlocked: set[str] = set()
        self._auto_unlock()

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

    # --- transitions (explicit only) ----------------------------------------

    def advance(self) -> Phase:
        if self.is_terminal:
            raise CaseComplete(f"case {self._case.meta.id!r} is at its final phase")
        self._i += 1
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
        self._transcript.append({"role": role, "content": content})

    def transcript_window(self) -> list[Message]:
        return self._transcript[-self._window :] if self._window > 0 else []

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
            return build_coach_context(
                self._case,
                phase_name=self.phase_name,
                unlocked_exhibit_ids=ids,
                transcript=window,
                stage_facts=facts,
                math_verdicts=math_verdicts,
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
