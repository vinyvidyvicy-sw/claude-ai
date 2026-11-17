"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent


class SettingsError(ValueError):
    pass


def _int(env: Mapping[str, str], key: str, default: int, minimum: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer") from exc
    if value < minimum:
        raise SettingsError(f"{key} must be >= {minimum}")
    return value


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path
    workflows_file: Path
    inventory_file: Path
    audit_jsonl_file: Path | None
    backend_poll_seconds: int
    backend_timeout_seconds: int
    session_idle_minutes: int
    session_absolute_hours: int
    max_failed_attempts: int
    lockout_minutes: int  # 0 = stay locked until an admin unlocks
    password_min_length: int
    cookie_secure: bool
    execution_mode: str  # "dry_run" (default) or "live"
    preview_ttl_minutes: int
    max_concurrent_runs: int
    app_title: str

    @property
    def live_writes_enabled(self) -> bool:
        return self.execution_mode == "live"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        def path(key: str, default: Path) -> Path:
            raw = env.get(key)
            p = Path(raw) if raw else default
            return p if p.is_absolute() else ROOT / p

        def opt_path(key: str) -> Path | None:
            raw = env.get(key)
            if not raw:
                return None
            p = Path(raw)
            return p if p.is_absolute() else ROOT / p

        mode = (env.get("PORTAL_EXECUTION_MODE") or "dry_run").strip().lower()
        if mode not in {"dry_run", "live"}:
            raise SettingsError("PORTAL_EXECUTION_MODE must be 'dry_run' or 'live'")
        return cls(
            db_path=path("PORTAL_DB_PATH", Path("data/portal.db")),
            workflows_file=path("PORTAL_WORKFLOWS_FILE", Path("config/workflows.yaml")),
            inventory_file=path("PORTAL_INVENTORY_FILE", Path("config/inventory.yaml")),
            audit_jsonl_file=opt_path("PORTAL_AUDIT_JSONL_FILE"),
            backend_poll_seconds=_int(env, "PORTAL_BACKEND_POLL_SECONDS", 3, 0),
            backend_timeout_seconds=_int(env, "PORTAL_BACKEND_TIMEOUT_SECONDS", 900, 1),
            session_idle_minutes=_int(env, "PORTAL_SESSION_IDLE_MINUTES", 15, 1),
            session_absolute_hours=_int(env, "PORTAL_SESSION_ABSOLUTE_HOURS", 8, 1),
            max_failed_attempts=_int(env, "PORTAL_MAX_FAILED_ATTEMPTS", 5, 1),
            lockout_minutes=_int(env, "PORTAL_LOCKOUT_MINUTES", 15, 0),
            password_min_length=_int(env, "PORTAL_PASSWORD_MIN_LENGTH", 12, 8),
            cookie_secure=_bool(env, "PORTAL_COOKIE_SECURE", True),
            execution_mode=mode,
            preview_ttl_minutes=_int(env, "PORTAL_PREVIEW_TTL_MINUTES", 30, 1),
            max_concurrent_runs=_int(env, "PORTAL_MAX_CONCURRENT_RUNS", 4, 1),
            app_title=env.get("PORTAL_TITLE") or "Cisco & Splunk Lab Portal",
        )
