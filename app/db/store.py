"""SQLite persistence for user data (02_ARCHITECTURE §6): sessions, turns,
scorecards, concept coverage, ladder state.

Native sqlite3, no ORM. Content is referenced by id string only — there is no
foreign key to content, so a deleted content file never orphans-crashes these
reads. The clock is injected for deterministic timestamps.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = Path(__file__).parent / "schema.sql"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        now: Callable[[], datetime] = _utcnow,
    ):
        self._now = now
        # check_same_thread=False: FastAPI runs sync endpoints in a worker thread,
        # so the connection must outlive its creating thread. Safe here because
        # this is a single-user app with sequential access (02_ARCHITECTURE §6).
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA.read_text())
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _ts(self) -> str:
        return self._now().isoformat()

    # --- sessions ------------------------------------------------------------

    def create_session(
        self, content_id: str, content_type: str, mode: str | None = None
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (content_id, content_type, mode, started_at) "
            "VALUES (?, ?, ?, ?)",
            (content_id, content_type, mode, self._ts()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def end_session(self, session_id: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?", (self._ts(), session_id)
        )
        self._conn.commit()

    def get_session(self, session_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    # --- turns ---------------------------------------------------------------

    def add_turn(
        self,
        session_id: int,
        role: str,
        text: str,
        *,
        phase: str | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO turns (session_id, role, text, ts, phase, provider, "
            "latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, text, self._ts(), phase, provider, latency_ms),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_turns(self, session_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- scorecards ----------------------------------------------------------

    def add_scorecard(
        self,
        session_id: int,
        dimension: str,
        score: int,
        evidence: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO scorecards (session_id, dimension, score, evidence, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, dimension, score, evidence, self._ts()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_scorecards(self, session_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM scorecards WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- concept coverage ----------------------------------------------------

    def add_concept_coverage(
        self, session_id: int, concept_id: str, score: int | None = None
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO concept_coverage (session_id, concept_id, score, "
            "created_at) VALUES (?, ?, ?, ?)",
            (session_id, concept_id, score, self._ts()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_concept_coverage(self, session_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM concept_coverage WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- ladder state --------------------------------------------------------

    def upsert_ladder(self, key: str, level: int, avg_score: float | None) -> None:
        self._conn.execute(
            "INSERT INTO ladder_state (key, level, avg_score, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET level = excluded.level, "
            "avg_score = excluded.avg_score, updated_at = excluded.updated_at",
            (key, level, avg_score, self._ts()),
        )
        self._conn.commit()

    def get_ladder(self, key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM ladder_state WHERE key = ?", (key,)
        ).fetchone()
        return dict(row) if row else None
