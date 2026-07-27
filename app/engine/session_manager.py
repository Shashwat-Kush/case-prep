"""Session manager (T-021): owns one session's persistence. Creates the session
row and records every turn to the store as it happens, so a completed run leaves
a complete, ordered transcript in the DB (provider + latency on assistant turns).
"""

from __future__ import annotations

from app.db.store import Store


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
