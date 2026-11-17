"""Application factory."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import audit, deps, inventory as inventory_mod, workflows as workflows_mod
from .credentials import CredentialStore
from .db import Database
from .runner import RunManager
from .settings import Settings

BASE = Path(__file__).resolve().parent
log = logging.getLogger("portal")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO)
    if not settings.cookie_secure:
        log.warning("PORTAL_COOKIE_SECURE=false: session cookies are NOT marked Secure. Development only.")

    app = FastAPI(title=settings.app_title, docs_url=None, redoc_url=None, openapi_url=None)
    db = Database(settings.db_path)
    audit.configure(settings.audit_jsonl_file)
    catalog = workflows_mod.load(settings.workflows_file)  # fails fast on a bad config
    inventory = inventory_mod.load(settings.inventory_file)
    credentials = CredentialStore(settings.secrets_dir)
    runs = RunManager(settings, db, catalog, inventory, credentials)
    runs.recover_interrupted()

    st = app.state
    st.settings, st.db, st.catalog, st.inventory = settings, db, catalog, inventory
    st.credentials, st.runs = credentials, runs
    st.templates = Jinja2Templates(directory=str(BASE / "templates"))

    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

    from .routes import admin, auth, dashboard, runs as runs_routes
    for module in (auth, dashboard, runs_routes, admin):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    # ---------------------------------------------------------------- errors
    @app.exception_handler(deps.LoginRequired)
    async def _login_required(request: Request, exc: deps.LoginRequired):
        if request.url.path.endswith(".json"):
            return PlainTextResponse("Session expired", status_code=401)
        return deps.login_redirect(exc.next_url, exc.expired)

    @app.exception_handler(deps.RedirectNeeded)
    async def _redirect(request: Request, exc: deps.RedirectNeeded):
        return RedirectResponse(exc.url, status_code=303)

    def _error(request: Request, code: int, title: str, message: str) -> HTMLResponse:
        return deps.render(request, "error.html", status_code=code, code=code, title=title,
                           message=message, principal=deps._principal(request, touch=False))

    @app.exception_handler(deps.Forbidden)
    async def _forbidden(request: Request, exc: deps.Forbidden):
        return _error(request, 403, "Not permitted", "Your role does not allow this action.")

    @app.exception_handler(deps.CsrfFailed)
    async def _csrf(request: Request, exc: deps.CsrfFailed):
        return _error(request, 403, "Request rejected",
                      "The form's security token was missing or invalid. Go back, reload the page and try again.")

    @app.exception_handler(404)
    async def _not_found(request: Request, exc):
        return _error(request, 404, "Page not found", "We could not find that page.")

    @app.exception_handler(500)
    async def _server_error(request: Request, exc):
        return _error(request, 500, "Something went wrong", "The error was logged. Please try again.")

    # ---------------------------------------------------------------- headers
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "same-origin"
        h["X-Frame-Options"] = "DENY"
        if settings.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000"
        if not request.url.path.startswith("/static/"):
            h["Cache-Control"] = "no-store"
        return response

    return app


def app_factory() -> FastAPI:  # for `uvicorn app.main:app_factory --factory`
    return create_app()
