"""Login, logout, password change."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from .. import audit, sessions, users
from ..deps import (LOGIN_CSRF_COOKIE_BASE, SESSION_COOKIE_BASE, Principal, client_ip, cookie_name,
                    csrf_form, render, require_user, safe_next, session_token)
from ..security import new_token, tokens_equal, verify_password

router = APIRouter()

GENERIC_FAILURE = ("Gagal masuk. Periksa nama pengguna dan kata sandi Anda. "
                   "Jika sudah mencoba beberapa kali, akun Anda mungkin terkunci; hubungi administrator.")


def _cookie_args(request: Request) -> dict:
    return dict(httponly=True, secure=request.app.state.settings.cookie_secure,
                samesite="lax", path="/")  # no max-age: browser-session cookie; server enforces idle timeout


@router.get("/login")
def login_form(request: Request, next: str = "/", expired: int = 0):
    token = new_token()
    resp = render(request, "login.html", login_csrf=token, next_url=safe_next(next),
                  notice="Sesi Anda telah berakhir. Silakan masuk kembali." if expired else None)
    resp.set_cookie(cookie_name(request, LOGIN_CSRF_COOKIE_BASE), token, **_cookie_args(request))
    return resp


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    st = request.app.state
    ip = client_ip(request)
    cookie_tok = request.cookies.get(cookie_name(request, LOGIN_CSRF_COOKIE_BASE), "")
    sent = form.get("csrf_token")
    if not cookie_tok or not isinstance(sent, str) or not tokens_equal(sent, cookie_tok):
        return render(request, "error.html", status_code=403, code=403, title="Permintaan ditolak",
                      message="Formulir masuk sudah kedaluwarsa. Muat ulang halaman lalu coba lagi.")
    username = str(form.get("username", ""))[:64].strip()
    password = str(form.get("password", ""))
    next_url = safe_next(str(form.get("next", "/")))

    with st.db.conn() as c:
        user, reason = users.authenticate(c, st.settings, username, password)
        audit.record(c, actor=username or "-", actor_role=user["role"] if user else None,
                     action="auth.login", result="success" if reason == "ok" else "failure",
                     detail=None if reason == "ok" else f"reason={reason}", ip=ip)
        if reason == "lockout":
            audit.record(c, actor=username, actor_role=user["role"], action="auth.lockout",
                         result="success", detail=f"locked after {user['failed_attempts']} failed attempts", ip=ip)
        if reason != "ok":
            token = new_token()
            resp = render(request, "login.html", status_code=401, login_csrf=token, next_url=next_url,
                          error=GENERIC_FAILURE, username=username)
            resp.set_cookie(cookie_name(request, LOGIN_CSRF_COOKIE_BASE), token, **_cookie_args(request))
            return resp
        sid, _csrf = sessions.create(c, user["id"], ip)
        sessions.purge_expired(c, st.settings)

    resp = RedirectResponse("/account/password" if user["must_change_password"] else next_url, status_code=303)
    resp.set_cookie(cookie_name(request, SESSION_COOKIE_BASE), sid, **_cookie_args(request))
    resp.delete_cookie(cookie_name(request, LOGIN_CSRF_COOKIE_BASE), path="/")
    return resp


@router.post("/logout")
async def logout(request: Request, form=Depends(csrf_form), p: Principal = Depends(require_user)):
    with request.app.state.db.conn() as c:
        sessions.destroy(c, session_token(request))
        audit.record(c, actor=p.username, actor_role=p.role, action="auth.logout", result="success", ip=p.ip)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(cookie_name(request, SESSION_COOKIE_BASE), path="/")
    return resp


@router.get("/account/password")
def password_form(request: Request, p: Principal = Depends(require_user)):
    return render(request, "password.html", principal=p, errors=[])


@router.post("/account/password")
async def password_submit(request: Request, form=Depends(csrf_form), p: Principal = Depends(require_user)):
    st = request.app.state
    current, new, again = (str(form.get(k, "")) for k in ("current_password", "new_password", "confirm_password"))
    errors: list[str] = []
    with st.db.conn() as c:
        user = users.get(c, p.user_id)
        ok, _ = verify_password(user["password_hash"], current)
        if not ok:
            errors.append("Kata sandi Anda saat ini salah.")
        if new != again:
            errors.append("Kata sandi baru tidak sama.")
        if new == current:
            errors.append("Pilih kata sandi yang berbeda dari yang sekarang.")
        if not errors:
            try:
                users.set_password(c, st.settings, p.user_id, new, must_change=False)
            except users.UserError as exc:
                errors.append(str(exc))
        if errors:
            audit.record(c, actor=p.username, actor_role=p.role, action="auth.password_change",
                         result="failure", ip=p.ip)
        else:
            sessions.destroy_for_user(c, p.user_id, except_token=session_token(request))
            sessions.set_flash(c, session_token(request), "Kata sandi berhasil diubah.")
            audit.record(c, actor=p.username, actor_role=p.role, action="auth.password_change",
                         result="success", ip=p.ip)
    if errors:
        return render(request, "password.html", principal=p, errors=errors, status_code=400)
    return RedirectResponse("/", status_code=303)
