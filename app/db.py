"""SQLite storage. Single-file DB, one short-lived connection per unit of work.

ASSUMPTION: a single portal instance. For multiple instances, move to PostgreSQL
(the SQL here is deliberately plain). Hosting environment is a TODO input.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash         TEXT NOT NULL,              -- argon2id, salted; never plaintext
    role                  TEXT NOT NULL CHECK (role IN ('admin','engineer','viewer')),
    is_active             INTEGER NOT NULL DEFAULT 1,
    failed_attempts       INTEGER NOT NULL DEFAULT 0,
    locked_until          TEXT,                       -- ISO-8601 UTC, NULL = not locked
    must_change_password  INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    created_by            TEXT,
    last_login_at         TEXT,
    password_changed_at   TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT PRIMARY KEY,                    -- sha256 of the cookie value
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    ip           TEXT,
    flash        TEXT                                 -- one-shot, non-secret message
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS runs (
    id             TEXT PRIMARY KEY,
    workflow_id    TEXT NOT NULL,
    platform       TEXT NOT NULL,
    workflow_hash  TEXT NOT NULL,                     -- definition hash at preview time
    user_id        INTEGER REFERENCES users(id),
    username       TEXT NOT NULL,
    params_json    TEXT NOT NULL,
    plan_json      TEXT NOT NULL,
    plan_hash      TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN
                     ('previewed','running','succeeded','failed','cancelled','expired')),
    mode           TEXT NOT NULL CHECK (mode IN ('dry_run','live')),
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    confirmed_at   TEXT,
    confirmed_by   TEXT,
    started_at     TEXT,
    finished_at    TEXT,
    result_summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);

CREATE TABLE IF NOT EXISTS run_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ts      TEXT NOT NULL,
    level   TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_log_run ON run_log(run_id, id);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,                        -- username, or '-' when unauthenticated
    actor_role  TEXT,
    action      TEXT NOT NULL,
    target      TEXT,
    params_json TEXT,                                 -- already redacted
    result      TEXT NOT NULL,
    detail      TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor);

-- Append-only: the application (and anything using this connection) cannot edit history.
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
