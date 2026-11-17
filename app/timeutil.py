"""Single clock source so tests can patch time (call timeutil.now(), never import now)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

FOREVER = "9999-12-31T00:00:00+00:00"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(now())


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def in_minutes(minutes: float) -> str:
    return iso(now() + timedelta(minutes=minutes))
