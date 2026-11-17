"""Run lifecycle: preview (dry-run) -> explicit confirm -> execute -> log.

Invariants enforced here, not just in the UI:
  * Nothing executes unless a run row is in status 'previewed' AND was confirmed by its owner.
  * The confirmed plan must hash-match what was previewed, and the workflow definition must be
    unchanged since the preview.
  * In the default execution mode (dry_run) no device is ever contacted.
  * In live mode a step runs only if its request is defined (not TODO) and an adapter is
    registered for its interface. No adapters ship with this repository (see README).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Callable, Protocol

from . import audit, timeutil
from .credentials import CredentialStore, Credentials
from .db import Database
from .inventory import Device, Inventory
from .redact import scrub_text
from .settings import Settings
from .workflows import Workflow, WorkflowCatalog, build_plan, plan_hash

log = logging.getLogger("portal.runner")


class Adapter(Protocol):
    """Implement one per confirmed device interface (e.g. RESTCONF) and register it.

    `request` is the operator-supplied, already-rendered request mapping from workflows.yaml.
    Return a short, human-readable result. Do not include secrets in it.
    """

    def execute(self, device: Device, credentials: Credentials, request: dict[str, Any]) -> str: ...


ADAPTERS: dict[str, Adapter] = {}  # interface name -> adapter. TODO: none confirmed yet.


def register_adapter(interface: str, adapter: Adapter) -> None:
    ADAPTERS[interface] = adapter


class RunError(Exception):
    """User-facing problem with a run request."""


class RunManager:
    def __init__(
        self, settings: Settings, db: Database, catalog: WorkflowCatalog,
        inventory: Inventory, credentials: CredentialStore,
    ):
        self.settings, self.db, self.catalog = settings, db, catalog
        self.inventory, self.credentials = inventory, credentials
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_runs, thread_name_prefix="run")
        # Tests replace this with a synchronous call.
        self.submit: Callable[[str], Any] = lambda run_id: self._pool.submit(self._execute, run_id)

    # ------------------------------------------------------------------ preview

    def create_preview(
        self, wf: Workflow, params: dict[str, Any], *, user_id: int, username: str, role: str, ip: str | None
    ) -> str:
        plan = build_plan(wf, params, self.inventory)
        run_id = uuid.uuid4().hex
        now = timeutil.now()
        mode = "live" if self.settings.live_writes_enabled else "dry_run"
        with self.db.conn() as c:
            c.execute(
                "INSERT INTO runs (id, workflow_id, platform, workflow_hash, user_id, username, params_json,"
                " plan_json, plan_hash, status, mode, created_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,'previewed',?,?,?)",
                (run_id, wf.id, wf.platform, wf.hash, user_id, username,
                 json.dumps(params, sort_keys=True, default=str), json.dumps(plan, default=str),
                 plan_hash(plan, params), mode, timeutil.iso(now),
                 timeutil.iso(now + timedelta(minutes=self.settings.preview_ttl_minutes))),
            )
            audit.record(c, actor=username, actor_role=role, action="workflow.preview", target=wf.id,
                         params=params, result="success", detail=f"run={run_id}", ip=ip)
        return run_id

    # ------------------------------------------------------------------ confirm

    def confirm(self, run_id: str, *, user_id: int, username: str, role: str, ip: str | None) -> None:
        error = self._confirm_tx(run_id, user_id=user_id, username=username, role=role, ip=ip)
        if error:  # raised after commit so status changes / audit rows made while refusing persist
            raise RunError(error)

    def _confirm_tx(self, run_id: str, *, user_id: int, username: str, role: str, ip: str | None) -> str | None:
        with self.db.conn() as c:
            run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                return "Run not found."
            if run["user_id"] != user_id:
                self._deny(c, username, role, run, ip, "not the user who created the preview")
                return "Only the user who created the preview can confirm it."
            if run["status"] != "previewed":
                return f"This run is already {run['status']}; start a new preview."
            if run["expires_at"] <= timeutil.now_iso():
                c.execute("UPDATE runs SET status='expired' WHERE id=?", (run_id,))
                return "This preview expired. Please preview again."
            wf = self.catalog.workflows.get(run["workflow_id"])
            params = json.loads(run["params_json"])
            plan = json.loads(run["plan_json"])
            if wf is None or wf.hash != run["workflow_hash"]:
                c.execute("UPDATE runs SET status='expired' WHERE id=?", (run_id,))
                return "The workflow definition changed since the preview. Please preview again."
            if plan_hash(plan, params) != run["plan_hash"]:
                c.execute("UPDATE runs SET status='failed', finished_at=?, result_summary='plan integrity check failed'"
                          " WHERE id=?", (timeutil.now_iso(), run_id))
                audit.record(c, actor=username, actor_role=role, action="workflow.confirm", target=run["workflow_id"],
                             result="denied", detail=f"run={run_id}: plan hash mismatch", ip=ip)
                return "The stored plan failed its integrity check; nothing was run."
            now = timeutil.now_iso()
            # Single conditional UPDATE makes a double-submit start the run only once.
            cur = c.execute(
                "UPDATE runs SET status='running', confirmed_at=?, confirmed_by=?, started_at=?"
                " WHERE id=? AND status='previewed'", (now, username, now, run_id))
            if cur.rowcount != 1:
                return "This run was already confirmed."
            audit.record(c, actor=username, actor_role=role, action="workflow.confirm", target=run["workflow_id"],
                         params=params, result="success", detail=f"run={run_id} mode={run['mode']}", ip=ip)
        self.log(run_id, "info", f"Confirmed by {username}. Mode: {run['mode']}.")
        self.submit(run_id)
        return None

    def cancel(self, run_id: str, *, user_id: int, username: str, role: str, ip: str | None) -> None:
        with self.db.conn() as c:
            run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None or run["user_id"] != user_id or run["status"] != "previewed":
                raise RunError("Nothing to cancel.")
            c.execute("UPDATE runs SET status='cancelled', finished_at=? WHERE id=?", (timeutil.now_iso(), run_id))
            audit.record(c, actor=username, actor_role=role, action="workflow.cancel", target=run["workflow_id"],
                         result="success", detail=f"run={run_id}", ip=ip)

    @staticmethod
    def _deny(c: sqlite3.Connection, username: str, role: str, run: sqlite3.Row, ip: str | None, why: str) -> None:
        audit.record(c, actor=username, actor_role=role, action="workflow.confirm", target=run["workflow_id"],
                     result="denied", detail=f"run={run['id']}: {why}", ip=ip)

    # ------------------------------------------------------------------ execution

    def log(self, run_id: str, level: str, message: str, hide: tuple[str, ...] = ()) -> None:
        with self.db.conn() as c:
            c.execute("INSERT INTO run_log (run_id, ts, level, message) VALUES (?,?,?,?)",
                      (run_id, timeutil.now_iso(), level, scrub_text(message, hide)[:2000]))

    def _execute(self, run_id: str) -> None:
        with self.db.conn() as c:
            run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        plan = json.loads(run["plan_json"])
        dry = run["mode"] != "live" or not self.settings.live_writes_enabled  # never escalate
        ok, summary = True, ""
        try:
            for step in plan["steps"]:
                self.log(run_id, "info", f"Step {step['id']}: {step['description']} [{step['target']}]")
                if dry:
                    self.log(run_id, "info", f"  DRY-RUN: no device contact. Would use interface "
                                             f"'{step['interface']}'" + ("." if step["request_defined"]
                                             else " (request definition is TODO)."))
                    continue
                ok, summary = self._run_live_step(run_id, step)
                if not ok:
                    break
            if ok:
                summary = ("Dry-run complete: no changes were sent to any device." if dry
                           else f"Completed {len(plan['steps'])} step(s).")
        except Exception as exc:  # defensive: never leave a run stuck in 'running'
            ok, summary = False, f"Unexpected error: {type(exc).__name__}"
            log.exception("run %s crashed", run_id)
        self._finish(run_id, run, ok, summary)

    def _run_live_step(self, run_id: str, step: dict[str, Any]) -> tuple[bool, str]:
        if not step["request_defined"]:
            self.log(run_id, "error", "  Refused: this step's request is TODO in workflows.yaml.")
            return False, f"Step {step['id']}: request definition is TODO"
        adapter = ADAPTERS.get(step["interface"])
        if adapter is None:
            self.log(run_id, "error", f"  Refused: no adapter registered for interface '{step['interface']}'.")
            return False, f"Step {step['id']}: no adapter for '{step['interface']}'"
        device = self.inventory.get(step["target"])
        if device is None:
            self.log(run_id, "error", "  Refused: target is not in the inventory.")
            return False, f"Step {step['id']}: unknown target"
        creds = self.credentials.get(device.credential_ref)
        if creds is None:
            self.log(run_id, "error", f"  Refused: credential '{device.credential_ref}' is not configured.")
            return False, f"Step {step['id']}: credential not configured"
        hide = creds.secret_values()
        try:
            result = adapter.execute(device, creds, step["request"])
        except Exception as exc:
            self.log(run_id, "error", f"  Failed: {type(exc).__name__}: {exc}", hide)
            return False, f"Step {step['id']} failed ({type(exc).__name__})"
        self.log(run_id, "info", f"  OK: {result}", hide)
        return True, ""

    def _finish(self, run_id: str, run: sqlite3.Row, ok: bool, summary: str) -> None:
        status = "succeeded" if ok else "failed"
        self.log(run_id, "info" if ok else "error", f"Run {status}. {summary}")
        with self.db.conn() as c:
            c.execute("UPDATE runs SET status=?, finished_at=?, result_summary=? WHERE id=?",
                      (status, timeutil.now_iso(), summary[:500], run_id))
            audit.record(c, actor=run["confirmed_by"] or run["username"], action="workflow.run",
                         target=run["workflow_id"], params=json.loads(run["params_json"]),
                         result=status, detail=f"run={run_id} mode={run['mode']}: {summary}")

    def recover_interrupted(self) -> int:
        """After a restart, mark runs that were mid-flight as failed (we cannot know how far they got)."""
        with self.db.conn() as c:
            rows = c.execute("SELECT * FROM runs WHERE status='running'").fetchall()
            for r in rows:
                c.execute("UPDATE runs SET status='failed', finished_at=?, result_summary=? WHERE id=?",
                          (timeutil.now_iso(), "interrupted by portal restart; verify device state manually", r["id"]))
                audit.record(c, actor="system", action="workflow.run", target=r["workflow_id"],
                             result="failed", detail=f"run={r['id']}: interrupted by restart")
        return len(rows)
