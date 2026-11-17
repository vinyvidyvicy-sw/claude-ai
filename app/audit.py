"""Append-only audit trail: who did what, when, with which parameters, and the result."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from . import timeutil
from .redact import redact, scrub_text

log = logging.getLogger("portal.audit")
_jsonl_path: Path | None = None


def configure(jsonl_path: Path | None) -> None:
    """Optional JSON-lines mirror, for shipping to a SIEM (e.g. Splunk forwarder)."""
    global _jsonl_path
    _jsonl_path = jsonl_path
    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)


def record(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    result: str,
    actor_role: str | None = None,
    target: str | None = None,
    params: dict[str, Any] | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    entry = {
        "ts": timeutil.now_iso(),
        "actor": actor or "-",
        "actor_role": actor_role,
        "action": action,
        "target": target,
        "params_json": json.dumps(redact(params), sort_keys=True) if params is not None else None,
        "result": result,
        "detail": scrub_text(detail)[:1000] if detail else None,
        "ip": ip,
    }
    conn.execute(
        "INSERT INTO audit_log (ts, actor, actor_role, action, target, params_json, result, detail, ip)"
        " VALUES (:ts, :actor, :actor_role, :action, :target, :params_json, :result, :detail, :ip)",
        entry,
    )
    if _jsonl_path:
        try:
            with _jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            log.exception("could not write audit JSONL mirror")
