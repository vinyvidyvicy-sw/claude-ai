"""Admin: user management and audit log viewer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, sessions, users
from ..deps import Principal, csrf_form, render, require_admin, session_token
from ..security import temporary_password

router = APIRouter(prefix="/admin")
PAGE = 50


@router.get("/users")
def user_list(request: Request, p: Principal = Depends(require_admin)):
    with request.app.state.db.conn() as c:
        rows = users.list_users(c)
    return render(request, "admin_users.html", principal=p, users=rows, is_locked=users.is_locked,
                  roles=users.ROLES, errors=[], form_username="")


@router.post("/users")
async def user_create(request: Request, form=Depends(csrf_form), p: Principal = Depends(require_admin)):
    st = request.app.state
    username = str(form.get("username", "")).strip()
    role = str(form.get("role", ""))
    temp = temporary_password(st.settings.password_min_length)
    try:
        with st.db.conn() as c:
            users.create_user(c, st.settings, username=username, password=temp, role=role,
                              created_by=p.username, must_change_password=True)
            audit.record(c, actor=p.username, actor_role=p.role, action="user.create", target=username,
                         params={"role": role}, result="success", ip=p.ip)
    except users.UserError as exc:
        with st.db.conn() as c:
            rows = users.list_users(c)
        return render(request, "admin_users.html", principal=p, users=rows, is_locked=users.is_locked,
                      roles=users.ROLES, errors=[str(exc)], form_username=username, status_code=400)
    # Shown once, in this response only; never stored in plaintext.
    return render(request, "admin_temp_password.html", principal=p, target=username, temp_password=temp,
                  verb="created")


@router.post("/users/{user_id}/{action}")
async def user_action(user_id: int, action: str, request: Request,
                      form=Depends(csrf_form), p: Principal = Depends(require_admin)):
    st = request.app.state
    if action not in {"disable", "enable", "reset", "unlock"}:
        raise HTTPException(404)
    with st.db.conn() as c:
        target = users.get(c, user_id)
        if target is None:
            raise HTTPException(404)
        name = target["username"]
        problem = None
        if action == "disable":
            if target["id"] == p.user_id:
                problem = "You cannot disable your own account."
            elif target["role"] == "admin" and target["is_active"] and users.active_admin_count(c) <= 1:
                problem = "You cannot disable the last active administrator."
        if problem:
            audit.record(c, actor=p.username, actor_role=p.role, action=f"user.{action}", target=name,
                         result="denied", detail=problem, ip=p.ip)
            sessions.set_flash(c, session_token(request), problem)
            return RedirectResponse("/admin/users", status_code=303)

        temp = None
        if action == "disable":
            users.set_active(c, user_id, False)
            sessions.destroy_for_user(c, user_id)
        elif action == "enable":
            users.set_active(c, user_id, True)
        elif action == "unlock":
            users.unlock(c, user_id)
        elif action == "reset":
            temp = temporary_password(st.settings.password_min_length)
            users.set_password(c, st.settings, user_id, temp, must_change=True)
            sessions.destroy_for_user(c, user_id)
        audit.record(c, actor=p.username, actor_role=p.role, action=f"user.{action}", target=name,
                     result="success", ip=p.ip)
        if temp is None:
            sessions.set_flash(c, session_token(request), f"User {name}: {action} done.")
    if temp is not None:
        return render(request, "admin_temp_password.html", principal=p, target=name, temp_password=temp,
                      verb="reset")
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/audit")
def audit_view(request: Request, actor: str = "", action: str = "", page: int = 1,
               p: Principal = Depends(require_admin)):
    page = max(page, 1)
    where, args = [], []
    if actor:
        where.append("actor = ?"); args.append(actor)
    if action:
        where.append("action = ?"); args.append(action)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with request.app.state.db.conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM audit_log {clause}", args).fetchone()[0]
        rows = c.execute(f"SELECT * FROM audit_log {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                         [*args, PAGE, (page - 1) * PAGE]).fetchall()
        actions = [r[0] for r in c.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    return render(request, "audit.html", principal=p, rows=rows, actor=actor, action=action,
                  actions=actions, page=page, pages=max(1, -(-total // PAGE)), total=total)
