"""Request-scoped helpers: authentication, role checks, CSRF, template rendering."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import FormData

from . import sessions
from .security import tokens_equal

SESSION_COOKIE_BASE = "portal_session"
LOGIN_CSRF_COOKIE_BASE = "portal_login_csrf"


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/", expired: bool = False):
        self.next_url, self.expired = next_url, expired


class Forbidden(Exception):
    pass


class CsrfFailed(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    csrf: str
    must_change_password: bool
    ip: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_run(self) -> bool:  # viewers are read-only
        return self.role in {"admin", "engineer"}


def cookie_name(request: Request, base: str) -> str:
    # __Host- prefix: browser enforces Secure, Path=/ and no Domain (only valid with Secure).
    return f"__Host-{base}" if request.app.state.settings.cookie_secure else base


def client_ip(request: Request) -> str | None:
    # Behind a reverse proxy run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy>.
    return request.client.host if request.client else None


def session_token(request: Request) -> str | None:
    return request.cookies.get(cookie_name(request, SESSION_COOKIE_BASE))


def _principal(request: Request, *, touch: bool) -> Principal | None:
    token = session_token(request)
    if not token:
        return None
    with request.app.state.db.conn() as c:
        row = sessions.lookup(c, request.app.state.settings, token, touch=touch)
    if row is None:
        return None
    return Principal(row["user_id"], row["username"], row["role"], row["csrf_token"],
                     bool(row["must_change_password"]), client_ip(request))


def _next(request: Request) -> str:
    return request.url.path + (f"?{request.url.query}" if request.url.query else "")


def require_user(request: Request) -> Principal:
    p = _principal(request, touch=True)
    if p is None:
        raise LoginRequired(_next(request), expired=session_token(request) is not None)
    if p.must_change_password and request.url.path not in {"/account/password", "/logout"}:
        raise RedirectNeeded("/account/password")
    return p


def require_user_no_touch(request: Request) -> Principal:
    """For background polling: must not keep an idle session alive."""
    p = _principal(request, touch=False)
    if p is None:
        raise LoginRequired(_next(request))
    return p


class RedirectNeeded(Exception):
    def __init__(self, url: str):
        self.url = url


def require_admin(p: Principal = Depends(require_user)) -> Principal:
    if not p.is_admin:
        raise Forbidden()
    return p


def require_runner(p: Principal = Depends(require_user)) -> Principal:
    if not p.can_run:
        raise Forbidden()
    return p


async def csrf_form(request: Request, p: Principal = Depends(require_user)) -> FormData:
    form = await request.form()
    sent = form.get("csrf_token")
    if not isinstance(sent, str) or not tokens_equal(sent, p.csrf):
        raise CsrfFailed()
    return form


def safe_next(value: str | None) -> str:
    """Only allow same-site relative redirects."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value \
            and not any(ch in value for ch in "\r\n"):
        return value
    return "/"


def login_redirect(next_url: str, expired: bool = False) -> RedirectResponse:
    q = f"?next={quote(next_url, safe='/')}" + ("&expired=1" if expired else "")
    return RedirectResponse(f"/login{q}", status_code=303)


def render(request: Request, template: str, *, principal: Principal | None = None,
           status_code: int = 200, **ctx) -> HTMLResponse:
    st = request.app.state
    flash = None
    if principal is not None:
        token = session_token(request)
        if token:
            with st.db.conn() as c:
                flash = sessions.pop_flash(c, token)
    ctx.update(principal=principal, csrf=principal.csrf if principal else None, flash=flash,
               app_title=st.settings.app_title, execution_mode=st.settings.execution_mode,
               idle_minutes=st.settings.session_idle_minutes)
    return st.templates.TemplateResponse(request, template, ctx, status_code=status_code)
