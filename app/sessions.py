"""Server-side sessions. The cookie holds a random token; only its SHA-256 is stored."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from . import timeutil
from .security import hash_token, new_token
from .settings import Settings


def create(conn: sqlite3.Connection, user_id: int, ip: str | None) -> tuple[str, str]:
    token, csrf = new_token(), new_token()
    now = timeutil.now_iso()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, csrf_token, created_at, last_seen, ip)"
        " VALUES (?,?,?,?,?,?)",
        (hash_token(token), user_id, csrf, now, now, ip),
    )
    return token, csrf


def lookup(
    conn: sqlite3.Connection, settings: Settings, token: str | None, *, touch: bool = True
) -> sqlite3.Row | None:
    """Return the joined session+user row if the session is valid; enforce idle/absolute timeouts."""
    if not token:
        return None
    th = hash_token(token)
    row = conn.execute(
        "SELECT s.*, u.username, u.role, u.is_active, u.must_change_password"
        " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (th,),
    ).fetchone()
    if row is None:
        return None
    now = timeutil.now()
    idle_ok = timeutil.parse(row["last_seen"]) + timedelta(minutes=settings.session_idle_minutes) > now
    abs_ok = timeutil.parse(row["created_at"]) + timedelta(hours=settings.session_absolute_hours) > now
    if not (idle_ok and abs_ok and row["is_active"]):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
        return None
    if touch:
        conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (timeutil.iso(now), th))
    return row


def destroy(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


def destroy_for_user(conn: sqlite3.Connection, user_id: int, *, except_token: str | None = None) -> None:
    keep = hash_token(except_token) if except_token else ""
    conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep))


def purge_expired(conn: sqlite3.Connection, settings: Settings) -> None:
    idle = timeutil.iso(timeutil.now() - timedelta(minutes=settings.session_idle_minutes))
    conn.execute("DELETE FROM sessions WHERE last_seen < ?", (idle,))


def set_flash(conn: sqlite3.Connection, token: str, message: str) -> None:
    conn.execute("UPDATE sessions SET flash=? WHERE token_hash=?", (message, hash_token(token)))


def pop_flash(conn: sqlite3.Connection, token: str) -> str | None:
    th = hash_token(token)
    row = conn.execute("SELECT flash FROM sessions WHERE token_hash=?", (th,)).fetchone()
    if row and row["flash"]:
        conn.execute("UPDATE sessions SET flash=NULL WHERE token_hash=?", (th,))
        return row["flash"]
    return None
