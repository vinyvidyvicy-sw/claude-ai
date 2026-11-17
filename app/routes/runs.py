"""Workflow form -> preview (dry-run) -> confirm -> run status/log."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..deps import (Principal, csrf_form, render, require_runner, require_user,
                    require_user_no_touch)
from ..runner import RunError
from ..workflows import validate_params

router = APIRouter()


def _workflow(request: Request, platform_id: str, wf_id: str):
    wf = request.app.state.catalog.workflows.get(wf_id)
    if wf is None or wf.platform != platform_id:
        raise HTTPException(404)
    return wf


def _form_ctx(request: Request, wf, values=None, errors=None):
    st = request.app.state
    return dict(workflow=wf, platform=st.catalog.platforms[wf.platform], values=values or {},
                errors=errors or {}, devices=st.inventory.for_platform(wf.platform))


@router.get("/p/{platform_id}/{wf_id}")
def workflow_form(platform_id: str, wf_id: str, request: Request, p: Principal = Depends(require_user)):
    wf = _workflow(request, platform_id, wf_id)
    defaults = {q.name: q.default for q in wf.params if q.default is not None}
    return render(request, "workflow_form.html", principal=p, **_form_ctx(request, wf, defaults))


@router.post("/p/{platform_id}/{wf_id}/preview")
async def preview(platform_id: str, wf_id: str, request: Request,
                  form=Depends(csrf_form), p: Principal = Depends(require_runner)):
    wf = _workflow(request, platform_id, wf_id)
    st = request.app.state
    raw = {k: v for k, v in form.items() if isinstance(v, str)}
    clean, errors = validate_params(wf, raw, st.inventory)
    if errors:
        return render(request, "workflow_form.html", principal=p, status_code=400,
                      **_form_ctx(request, wf, raw, errors))
    run_id = st.runs.create_preview(wf, clean, user_id=p.user_id, username=p.username, role=p.role, ip=p.ip)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


def _load_run(request: Request, run_id: str):
    with request.app.state.db.conn() as c:
        run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        logs = c.execute("SELECT ts, level, message FROM run_log WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    if run is None:
        raise HTTPException(404)
    return run, logs


@router.get("/runs/{run_id}")
def run_page(run_id: str, request: Request, p: Principal = Depends(require_user)):
    run, logs = _load_run(request, run_id)
    st = request.app.state
    wf = st.catalog.workflows.get(run["workflow_id"])
    return render(request, "run.html", principal=p, run=run, logs=logs, workflow=wf,
                  plan=json.loads(run["plan_json"]), params=json.loads(run["params_json"]),
                  platform=st.catalog.platforms.get(run["platform"]),
                  can_confirm=(run["status"] == "previewed" and run["user_id"] == p.user_id and p.can_run),
                  live=st.settings.live_writes_enabled)


@router.get("/runs/{run_id}/status.json")
def run_status(run_id: str, request: Request, after: int = 0, p: Principal = Depends(require_user_no_touch)):
    with request.app.state.db.conn() as c:
        run = c.execute("SELECT status, result_summary FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(404)
        rows = c.execute("SELECT id, ts, level, message FROM run_log WHERE run_id=? AND id>? ORDER BY id",
                         (run_id, after)).fetchall()
    return JSONResponse({"status": run["status"], "summary": run["result_summary"],
                         "lines": [dict(r) for r in rows]})


@router.post("/runs/{run_id}/confirm")
async def confirm(run_id: str, request: Request, form=Depends(csrf_form), p: Principal = Depends(require_runner)):
    try:
        request.app.state.runs.confirm(run_id, user_id=p.user_id, username=p.username, role=p.role, ip=p.ip)
    except RunError as exc:
        run, logs = _load_run(request, run_id)
        st = request.app.state
        return render(request, "run.html", principal=p, run=run, logs=logs, error=str(exc), status_code=409,
                      workflow=st.catalog.workflows.get(run["workflow_id"]),
                      plan=json.loads(run["plan_json"]), params=json.loads(run["params_json"]),
                      platform=st.catalog.platforms.get(run["platform"]), can_confirm=False,
                      live=st.settings.live_writes_enabled)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, request: Request, form=Depends(csrf_form), p: Principal = Depends(require_runner)):
    try:
        request.app.state.runs.cancel(run_id, user_id=p.user_id, username=p.username, role=p.role, ip=p.ip)
    except RunError:
        pass
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@router.get("/runs")
def run_history(request: Request, p: Principal = Depends(require_user)):
    with request.app.state.db.conn() as c:
        rows = c.execute(
            "SELECT id, workflow_id, platform, username, status, mode, created_at, result_summary"
            " FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
    return render(request, "runs.html", principal=p, runs=rows, catalog=request.app.state.catalog)
