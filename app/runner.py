"""Run lifecycle: preview -> explicit confirm -> hand off to the automation backend -> follow status.

This portal is a FRONT END. It never connects to a device and holds no device credentials.
A confirmed request is submitted to an automation backend (e.g. an orchestration/automation
platform) that performs the change; the portal records the request and mirrors the backend's
status and log.

Invariants enforced here, not just in the UI:
  * Nothing is submitted unless a run row is 'previewed' AND confirmed by its owner.
  * The confirmed plan must hash-match what was previewed, and the workflow definition must be
    unchanged since the preview.
  * In the default mode (dry_run) nothing is sent to the backend at all.
  * In live mode the request is submitted only if the workflow's dispatch is defined (not TODO)
    and a backend is registered under that name. No backend ships with this repository.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Protocol

from . import audit, timeutil
from .db import Database
from .inventory import Inventory
from .redact import scrub_text
from .settings import Settings
from .workflows import WorkflowCatalog, Workflow, build_plan, plan_hash

log = logging.getLogger("portal.runner")
STATUS_ID = {"succeeded": "berhasil", "failed": "gagal"}


@dataclass
class JobStatus:
    state: str  # "pending" | "running" | "succeeded" | "failed"
    lines: list[str] = field(default_factory=list)  # the backend's full log so far
    summary: str = ""


class Backend(Protocol):
    """Implement once per automation backend and register it with register_backend().

    `job` carries: run_id (use as an idempotency key), requested_by, workflow_id, platform,
    backend_job (the workflow's dispatch.job), targets, payload. Authenticate to the backend
    with a service credential read from the environment/secret store inside your implementation;
    never put it in a log line or return value. Device credentials stay inside the backend.
    """

    def submit(self, job: dict[str, Any]) -> str: ...  # returns the backend's job id

    def poll(self, job_id: str) -> JobStatus: ...


BACKENDS: dict[str, Backend] = {}  # TODO: none confirmed yet


def register_backend(name: str, backend: Backend) -> None:
    BACKENDS[name] = backend


class RunError(Exception):
    """User-facing problem with a run request."""


class RunManager:
    def __init__(
        self, settings: Settings, db: Database, catalog: WorkflowCatalog, inventory: Inventory,
    ):
        self.settings, self.db, self.catalog = settings, db, catalog
        self.inventory = inventory
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
                return "Proses tidak ditemukan."
            if run["user_id"] != user_id:
                self._deny(c, username, role, run, ip, "not the user who created the preview")
                return "Hanya pengguna yang membuat pratinjau yang dapat mengonfirmasinya."
            if run["status"] != "previewed":
                return f"Proses ini sudah berstatus {run['status']}; buat pratinjau baru."
            if run["expires_at"] <= timeutil.now_iso():
                c.execute("UPDATE runs SET status='expired' WHERE id=?", (run_id,))
                return "Pratinjau ini sudah kedaluwarsa. Silakan buat pratinjau lagi."
            wf = self.catalog.workflows.get(run["workflow_id"])
            params = json.loads(run["params_json"])
            plan = json.loads(run["plan_json"])
            if wf is None or wf.hash != run["workflow_hash"]:
                c.execute("UPDATE runs SET status='expired' WHERE id=?", (run_id,))
                return "Definisi workflow berubah sejak pratinjau dibuat. Silakan buat pratinjau lagi."
            if plan_hash(plan, params) != run["plan_hash"]:
                c.execute("UPDATE runs SET status='failed', finished_at=?, result_summary='plan integrity check failed'"
                          " WHERE id=?", (timeutil.now_iso(), run_id))
                audit.record(c, actor=username, actor_role=role, action="workflow.confirm", target=run["workflow_id"],
                             result="denied", detail=f"run={run_id}: plan hash mismatch", ip=ip)
                return "Rencana yang tersimpan gagal pemeriksaan integritas; tidak ada yang dijalankan."
            now = timeutil.now_iso()
            # Single conditional UPDATE makes a double-submit start the run only once.
            cur = c.execute(
                "UPDATE runs SET status='running', confirmed_at=?, confirmed_by=?, started_at=?"
                " WHERE id=? AND status='previewed'", (now, username, now, run_id))
            if cur.rowcount != 1:
                return "Proses ini sudah dikonfirmasi."
            audit.record(c, actor=username, actor_role=role, action="workflow.confirm", target=run["workflow_id"],
                         params=params, result="success", detail=f"run={run_id} mode={run['mode']}", ip=ip)
        self.log(run_id, "info", f"Dikonfirmasi oleh {username}. Mode: {run['mode']}.")
        self.submit(run_id)
        return None

    def cancel(self, run_id: str, *, user_id: int, username: str, role: str, ip: str | None) -> None:
        with self.db.conn() as c:
            run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None or run["user_id"] != user_id or run["status"] != "previewed":
                raise RunError("Tidak ada yang dapat dibatalkan.")
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
                self.log(run_id, "info", f"Diminta: {step['description']} [{step['target']}]")
            d = plan["dispatch"]
            if dry:
                self.log(run_id, "info", "DRY-RUN: tidak ada yang dikirim ke backend otomasi "
                                         "dan tidak ada perangkat yang dihubungi.")
                summary = "Dry-run selesai: tidak ada permintaan yang dikirim ke backend; tidak ada perangkat yang diubah."
            else:
                ok, summary = self._dispatch(run_id, run, plan, d)
        except Exception as exc:  # defensive: never leave a run stuck in 'running'
            ok, summary = False, f"Kesalahan tak terduga: {type(exc).__name__}"
            log.exception("run %s crashed", run_id)
        self._finish(run_id, run, ok, summary)

    def _dispatch(self, run_id: str, run: sqlite3.Row, plan: dict[str, Any], d: dict[str, Any]) -> tuple[bool, str]:
        if not d["defined"]:
            self.log(run_id, "error", "Ditolak: dispatch (backend/job) workflow ini masih TODO di workflows.yaml.")
            return False, "dispatch backend/job masih TODO"
        backend = BACKENDS.get(d["backend"])
        if backend is None:
            self.log(run_id, "error", f"Ditolak: tidak ada backend terdaftar dengan nama '{d['backend']}'.")
            return False, f"tidak ada backend '{d['backend']}'"
        job = {"run_id": run_id, "requested_by": run["confirmed_by"], "workflow_id": run["workflow_id"],
               "platform": run["platform"], "backend_job": d["job"],
               "targets": sorted({s["target"] for s in plan["steps"] if s["target"]}),
               "payload": d["payload"]}
        try:
            job_id = backend.submit(job)
        except Exception as exc:
            self.log(run_id, "error", f"Backend menolak permintaan: {type(exc).__name__}: {exc}")
            return False, f"pengiriman ke backend gagal ({type(exc).__name__})"
        with self.db.conn() as c:
            c.execute("UPDATE runs SET backend_job_id=? WHERE id=?", (str(job_id), run_id))
        self.log(run_id, "info", f"Dikirim ke backend '{d['backend']}'. ID job backend: {job_id}")

        deadline = time.monotonic() + self.settings.backend_timeout_seconds
        seen = 0
        while True:
            try:
                st = backend.poll(job_id)
            except Exception as exc:
                self.log(run_id, "error", f"Tidak dapat membaca status backend: {type(exc).__name__}: {exc}")
                return False, f"kehilangan kontak dengan backend; periksa job {job_id} di sana"
            for line in st.lines[seen:]:
                self.log(run_id, "info", f"[backend] {line}")
            seen = len(st.lines)
            if st.state == "succeeded":
                return True, st.summary or f"Job backend {job_id} berhasil."
            if st.state == "failed":
                return False, st.summary or f"Job backend {job_id} gagal."
            if time.monotonic() > deadline:
                self.log(run_id, "error", "Berhenti menunggu backend. Job mungkin masih berjalan di sana.")
                return False, f"batas waktu menunggu habis; periksa job backend {job_id}"
            time.sleep(self.settings.backend_poll_seconds)

    def _finish(self, run_id: str, run: sqlite3.Row, ok: bool, summary: str) -> None:
        status = "succeeded" if ok else "failed"
        self.log(run_id, "info" if ok else "error", f"Proses {STATUS_ID[status]}. {summary}")
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
                          (timeutil.now_iso(), "terhenti karena portal dimulai ulang; periksa job di backend untuk hasil sebenarnya", r["id"]))
                audit.record(c, actor="system", action="workflow.run", target=r["workflow_id"],
                             result="failed", detail=f"run={r['id']}: interrupted by restart")
        return len(rows)
