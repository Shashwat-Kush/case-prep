-- User data only (02_ARCHITECTURE §6). Content lives in files and is referenced
-- by id string only: there is deliberately no foreign key to any content table,
-- so editing or deleting a content file never touches or breaks this history.

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id   TEXT NOT NULL,   -- e.g. 'case-brewbar-diagnostic' (no FK by design)
    content_type TEXT NOT NULL,   -- case | guesstimate | lesson
    mode         TEXT,            -- guided | standard | cold | coached | timed
    started_at   TEXT NOT NULL,   -- ISO-8601
    ended_at     TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,     -- user | assistant | system
    text       TEXT NOT NULL,
    ts         TEXT NOT NULL,     -- ISO-8601
    phase      TEXT,
    provider   TEXT,
    latency_ms REAL
);

CREATE TABLE IF NOT EXISTS scorecards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    dimension  TEXT NOT NULL,     -- structure | math | judgment | ...
    score      INTEGER NOT NULL,  -- 1..5
    evidence   TEXT,              -- quoted evidence from the transcript
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concept_coverage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL,
    score      INTEGER,           -- optional mastery signal
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ladder_state (
    key        TEXT PRIMARY KEY,  -- e.g. 'case:profitability' or 'global'
    level      INTEGER NOT NULL DEFAULT 0,
    avg_score  REAL,
    updated_at TEXT NOT NULL
);

-- LLM-free mental-math sprints (T-063). Self-contained: no session link, so
-- drills work fully offline and independently of case/lesson history.
CREATE TABLE IF NOT EXISTS drill_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,     -- percent | breakeven | growth | division | mixed
    total      INTEGER NOT NULL,
    correct    INTEGER NOT NULL,
    elapsed_ms REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_scorecards_session ON scorecards(session_id);
CREATE INDEX IF NOT EXISTS idx_coverage_session ON concept_coverage(session_id);
