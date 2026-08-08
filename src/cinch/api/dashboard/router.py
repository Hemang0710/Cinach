"""Dashboard HTTP routes (Phase 10).

Five endpoints, all under ``/dashboard``:

- ``GET /dashboard/login?token=...`` — verify the magic-link token, set the
  session cookie, redirect to ``/dashboard``.
- ``GET /dashboard`` — render the main HTML page (requires session cookie).
- ``GET /dashboard/fragments/summary`` — HTML fragment for HTMX polling (counts).
- ``GET /dashboard/fragments/applications`` — HTML fragment for HTMX polling (table).
- ``GET /dashboard/logout`` — clear the cookie, redirect to a login-error page.

Auth: the magic-link token is issued by the bot's ``/dashboard`` command
(:mod:`cinch.bot.handlers`). ``verify_token`` in :mod:`.auth` covers signing and
expiry. The session cookie is a longer-lived token with the same wire format,
signed by the same derived key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Cookie, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from cinch.api.dashboard.auth import (
    MAGIC_LINK_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    InvalidTokenError,
    sign_token,
    verify_token,
)
from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.db.session import Database
from cinch.services.dashboard_stats import compute_dashboard_stats

logger = get_logger(__name__)

SESSION_COOKIE_NAME = "cinch_session"
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _templates() -> Jinja2Templates:
    """Lazy-loaded Jinja env — reads from the packaged templates directory."""
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _authorized_user(cookie_value: str | None, settings: Settings) -> UUID | None:
    """Verify the session cookie; return the user id or ``None`` if invalid/absent."""
    if not cookie_value or not settings.telegram_webhook_secret:
        return None
    try:
        return verify_token(cookie_value, settings.telegram_webhook_secret).user_id
    except InvalidTokenError:
        return None


def _login_error(reason: str, status_code: int = 401) -> HTMLResponse:
    """Render the login-error page with a short explanatory ``reason``."""
    tpl = _templates().get_template("login_error.html")
    return HTMLResponse(tpl.render(reason=reason), status_code=status_code)


def _get_db(request: Request) -> Database:
    """Pull the injected ``Database`` off ``app.state`` (set by the app factory)."""
    db: Database | None = request.app.state.db
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")
    return db


def _get_settings(request: Request) -> Settings:
    """The active ``Settings`` used to build this app (stored on ``app.state``)."""
    settings: Settings = request.app.state.settings
    return settings


def build_dashboard_router() -> APIRouter:
    """Construct the ``/dashboard/*`` router. The app factory mounts it once."""
    router = APIRouter(prefix="/dashboard", tags=["dashboard"])

    @router.get("/login", response_class=HTMLResponse)
    async def login(request: Request, token: str = Query(...)) -> Any:
        """Consume a magic-link token; set the session cookie; redirect."""
        settings = _get_settings(request)
        if not settings.telegram_webhook_secret:
            return _login_error("unavailable — TELEGRAM_WEBHOOK_SECRET is not set", 503)
        try:
            payload = verify_token(token, settings.telegram_webhook_secret)
        except InvalidTokenError as exc:
            return _login_error("expired" if "expired" in str(exc) else "invalid")

        session = sign_token(payload.user_id, SESSION_TTL_SECONDS, settings.telegram_webhook_secret)
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
        )
        logger.info("dashboard_login", user_id=str(payload.user_id))
        return response

    @router.get("/logout", response_class=HTMLResponse)
    async def logout() -> Any:
        """Clear the session cookie and drop the caller on the login-error page."""
        response = _login_error("cleared")
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request, cinch_session: str | None = Cookie(default=None)) -> Any:
        """The main dashboard page — HTMX fragments load in on page load."""
        settings = _get_settings(request)
        user_id = _authorized_user(cinch_session, settings)
        if user_id is None:
            return _login_error("required — please request a fresh link", 401)
        db = _get_db(request)
        async with db.session() as session:
            stats = await compute_dashboard_stats(session, user_id)
        tpl = _templates().get_template("dashboard.html")
        return HTMLResponse(tpl.render(request=request, stats=stats))

    @router.get("/fragments/summary", response_class=HTMLResponse)
    async def fragment_summary(
        request: Request, cinch_session: str | None = Cookie(default=None)
    ) -> Any:
        """HTMX poll target — just the summary tiles."""
        settings = _get_settings(request)
        user_id = _authorized_user(cinch_session, settings)
        if user_id is None:
            raise HTTPException(status_code=401)
        db = _get_db(request)
        async with db.session() as session:
            stats = await compute_dashboard_stats(session, user_id)
        tpl = _templates().get_template("_summary.html")
        return HTMLResponse(tpl.render(stats=stats))

    @router.get("/fragments/applications", response_class=HTMLResponse)
    async def fragment_applications(
        request: Request, cinch_session: str | None = Cookie(default=None)
    ) -> Any:
        """HTMX poll target — just the applications table."""
        settings = _get_settings(request)
        user_id = _authorized_user(cinch_session, settings)
        if user_id is None:
            raise HTTPException(status_code=401)
        db = _get_db(request)
        async with db.session() as session:
            stats = await compute_dashboard_stats(session, user_id)
        tpl = _templates().get_template("_applications.html")
        return HTMLResponse(tpl.render(stats=stats))

    return router


def issue_magic_link(user_id: UUID, settings: Settings) -> str:
    """Build the absolute magic-link URL the bot DMs to the user.

    Returns a full HTTPS URL: ``{TELEGRAM_WEBHOOK_URL}/dashboard/login?token=<t>``.
    Raises ``RuntimeError`` when ``TELEGRAM_WEBHOOK_URL`` or the signing secret
    isn't configured — the caller should surface a clear error.
    """
    if not settings.telegram_webhook_secret:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required to issue magic-links")
    if not settings.telegram_webhook_url:
        raise RuntimeError("TELEGRAM_WEBHOOK_URL is required so the link points at the deploy")
    token = sign_token(user_id, MAGIC_LINK_TTL_SECONDS, settings.telegram_webhook_secret)
    base = settings.telegram_webhook_url.rstrip("/")
    return f"{base}/dashboard/login?token={token}"
