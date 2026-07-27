"""Session manager (T-021): owns one session's persistence. Creates the session
row and records every turn to the store as it happens, so a completed run leaves
a complete, ordered transcript in the DB (provider + latency on assistant turns).

DiagnosticSession (T-027) is the zero-stakes baseline: a diagnostic-flagged case
plus two guesstimates run as one session. Scores are always stored; whether they
are shown is gated by config.score_visibility (hidden for the first sessions,
PRD §5). Completing it seeds ladder_state so the dashboard has a starting point.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.db.store import Store
from app.engine.content_loader import ContentLibrary
from app.engine.content_models import Case, Guesstimate
from app.engine.scoring import Scorecard, persist_scorecard

DIAGNOSTIC_LADDER_KEY = "global"


class SessionManager:
    def __init__(
        self,
        store: Store,
        *,
        content_id: str,
        content_type: str,
        mode: str | None = None,
    ):
        self._store = store
        self._session_id = store.create_session(content_id, content_type, mode)

    @property
    def session_id(self) -> int:
        return self._session_id

    @property
    def store(self) -> Store:
        return self._store

    def record_turn(
        self,
        role: str,
        text: str,
        *,
        phase: str | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> int:
        return self._store.add_turn(
            self._session_id,
            role,
            text,
            phase=phase,
            provider=provider,
            latency_ms=latency_ms,
        )

    def end(self) -> None:
        self._store.end_session(self._session_id)


# --- Diagnostic baseline (T-027) ---------------------------------------------


@dataclass(frozen=True)
class DiagnosticPlan:
    """What the diagnostic runs: one flagged case and its guesstimates."""

    case: Case
    guesstimates: list[Guesstimate]


def select_diagnostic_content(
    library: ContentLibrary, *, num_guesstimates: int = 2
) -> DiagnosticPlan:
    """Pick the diagnostic-flagged case plus up to `num_guesstimates` flagged
    guesstimates, in deterministic id order (PRD §5)."""
    cases = sorted(
        (c for c in library.cases.values() if c.meta.diagnostic),
        key=lambda c: c.meta.id,
    )
    if not cases:
        raise ValueError("no diagnostic-flagged case in the library")
    guesses = sorted(
        (g for g in library.guesstimates.values() if g.meta.diagnostic),
        key=lambda g: g.meta.id,
    )
    return DiagnosticPlan(cases[0], guesses[:num_guesstimates])


class DiagnosticSession:
    """One session spanning the diagnostic case + guesstimates. Scores are always
    persisted; display is gated by config.score_visibility."""

    def __init__(self, store: Store, plan: DiagnosticPlan, *, config: Config):
        self._store = store
        self._config = config
        self._session_id = store.create_session(plan.case.meta.id, "diagnostic")

    @property
    def session_id(self) -> int:
        return self._session_id

    @property
    def scores_visible(self) -> bool:
        return self._config.score_visibility

    def record_scorecard(self, scorecard: Scorecard) -> Scorecard | None:
        """Persist every dimension regardless of visibility (zero-stakes but still
        recorded). Return the scorecard only when scores are visible, so the caller
        shows nothing while scores are hidden."""
        persist_scorecard(self._store, self._session_id, scorecard)
        return scorecard if self.scores_visible else None

    def seed_ladder(self, avg_score: float | None, *, level: int = 0) -> None:
        self._store.upsert_ladder(DIAGNOSTIC_LADDER_KEY, level, avg_score)

    def end(self) -> None:
        self._store.end_session(self._session_id)
