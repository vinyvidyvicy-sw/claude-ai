"""User store: creation, authentication with lockout, password changes."""
from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from typing import Literal

from . import timeutil
from .security import hash_password, password_problems, verify_password
from .settings import Settings

ROLES = ("admin", "engineer", "viewer")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")

AuthReason = Literal["ok", "unknown", "bad_password", "locked", "lockout", "disabled"]


class UserError(ValueError):
    pass


def get_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()


def active_admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
    ).fetchone()[0]


def create_user(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    username: str,
    password: str,
    role: str,
    created_by: str | None,
    must_change_password: bool,
) -> int:
    if not USERNAME_RE.match(username):
        raise UserError("Nama pengguna harus 3-32 karakter: huruf, angka, '.', '_' atau '-'.")
    if role not in ROLES:
        raise UserError("Peran tidak dikenal.")
    problems = password_problems(password, username, settings.password_min_length)
    if problems:
        raise UserError(" ".join(problems))
    if get_by_username(conn, username):
        raise UserError("Nama pengguna itu sudah ada.")
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, must_change_password, created_at, created_by,"
        " password_changed_at) VALUES (?,?,?,?,?,?,?)",
        (username, hash_password(password), role, int(must_change_password),
         timeutil.now_iso(), created_by, timeutil.now_iso()),
    )
    return int(cur.lastrowid)


def authenticate(
    conn: sqlite3.Connection, settings: Settings, username: str, password: str
) -> tuple[sqlite3.Row | None, AuthReason]:
    """Check credentials and enforce lockout. Caller shows one generic message for all failures."""
    user = get_by_username(conn, username)
    ok, needs_rehash = verify_password(user["password_hash"] if user else None, password)
    if user is None:
        return None, "unknown"

    now = timeutil.now()
    if user["locked_until"]:
        if timeutil.parse(user["locked_until"]) > now:
            return user, "locked"  # even a correct password is refused while locked
        conn.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE id=?", (user["id"],))
        user = get(conn, user["id"])

    if not user["is_active"]:
        return user, "disabled"

    if not ok:
        attempts = user["failed_attempts"] + 1
        locked_until = None
        if attempts >= settings.max_failed_attempts:
            locked_until = (
                timeutil.FOREVER
                if settings.lockout_minutes == 0
                else timeutil.iso(now + timedelta(minutes=settings.lockout_minutes))
            )
        conn.execute(
            "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
            (attempts, locked_until, user["id"]),
        )
        return get(conn, user["id"]), ("lockout" if locked_until else "bad_password")  # "lockout" = this attempt tripped it

    conn.execute(
        "UPDATE users SET failed_attempts=0, locked_until=NULL, last_login_at=? WHERE id=?",
        (timeutil.iso(now), user["id"]),
    )
    if needs_rehash:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user["id"]))
    return get(conn, user["id"]), "ok"


def set_password(
    conn: sqlite3.Connection, settings: Settings, user_id: int, new_password: str,
    *, must_change: bool,
) -> None:
    user = get(conn, user_id)
    problems = password_problems(new_password, user["username"], settings.password_min_length)
    if problems:
        raise UserError(" ".join(problems))
    conn.execute(
        "UPDATE users SET password_hash=?, must_change_password=?, password_changed_at=?,"
        " failed_attempts=0, locked_until=NULL WHERE id=?",
        (hash_password(new_password), int(must_change), timeutil.now_iso(), user_id),
    )


def set_active(conn: sqlite3.Connection, user_id: int, active: bool) -> None:
    conn.execute(
        "UPDATE users SET is_active=?, failed_attempts=0, locked_until=NULL WHERE id=?",
        (int(active), user_id),
    )


def unlock(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (user_id,))


def is_locked(user: sqlite3.Row) -> bool:
    return bool(user["locked_until"]) and timeutil.parse(user["locked_until"]) > timeutil.now()
