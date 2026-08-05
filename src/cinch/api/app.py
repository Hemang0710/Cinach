"""FastAPI application factory.

Exposes health probes and, when a Telegram bot token is configured, the
secret-token-verified webhook. A ``lifespan`` owns the async ``Database`` and the
PTB ``Application`` it creates (initialize/start on boot, stop/dispose on shutdown);
tests inject their own ``db``/``bot_app`` instead, which the factory places on
``app.state`` immediately so no live bot or lifespan run is required.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from cinch import __version__
from cinch.api.webhook import register_webhook
from cinch.bot.application import build_bot_application
from cinch.core.config import Settings, get_settings
from cinch.core.crypto import validate_encryption_key
from cinch.core.logging import configure_logging, get_logger
from cinch.core.observability import init_sentry
from cinch.db.session import Database

logger = get_logger(__name__)


class HealthResponse(BaseModel):
    """Response body for the liveness probe."""

    status: Literal["ok"] = "ok"
    version: str


class ReadyResponse(BaseModel):
    """Response body for the readiness probe."""

    status: Literal["ready"] = "ready"


def create_app(
    settings: Settings | None = None,
    *,
    db: Database | None = None,
    bot_app: Any | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        settings: Optional settings override (defaults to the cached env settings).
        db: Optional injected database (tests). When given, the lifespan does not
            create or dispose it.
        bot_app: Optional injected PTB application (tests). When given, the lifespan
            does not build, start, or stop it.
    """
    settings = settings or get_settings()
    configure_logging(log_level=settings.log_level, json_logs=settings.log_json)
    init_sentry(settings)
    # Fail fast on a malformed ENCRYPTION_KEY — otherwise the first resume upload
    # crashes inside SQLAlchemy with no user-facing error and nothing is saved.
    validate_encryption_key(settings.encryption_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_db = app.state.db is None
        if owns_db:
            app.state.db = Database(settings.database_url)

        owns_bot = app.state.bot_app is None and bool(settings.telegram_bot_token)
        if owns_bot:
            app.state.bot_app = build_bot_application(settings, app.state.db)
            await app.state.bot_app.initialize()
            await app.state.bot_app.start()
            if settings.telegram_webhook_url:
                await app.state.bot_app.bot.set_webhook(
                    url=settings.telegram_webhook_url.rstrip("/") + settings.telegram_webhook_path,
                    secret_token=settings.telegram_webhook_secret,
                )

        # Background schedulers: each runs only when explicitly enabled and a bot exists.
        schedulers: list[Any] = []
        if app.state.bot_app is not None:
            from cinch.api.scheduler import (
                start_discovery_scheduler,
                start_submission_scheduler,
            )

            bot = app.state.bot_app.bot
            if settings.discovery_enabled:
                schedulers.append(start_discovery_scheduler(app.state.db, settings, bot))
            if settings.submission_enabled:
                schedulers.append(start_submission_scheduler(app.state.db, settings, bot))
        try:
            yield
        finally:
            for scheduler in schedulers:
                scheduler.shutdown(wait=False)
            if owns_bot and app.state.bot_app is not None:
                await app.state.bot_app.stop()
                await app.state.bot_app.shutdown()
            if owns_db and app.state.db is not None:
                await app.state.db.dispose()

    app = FastAPI(
        title="Cinch",
        version=__version__,
        summary="Human-in-the-loop job application assistant.",
        lifespan=lifespan,
    )
    # Injected dependencies are visible immediately (tests don't run the lifespan).
    app.state.db = db
    app.state.bot_app = bot_app

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Bind a correlation id to structlog for the request; echo it back."""
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        """Liveness probe: the process is up and serving requests."""
        return HealthResponse(version=__version__)

    @app.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        """Readiness probe: verifies the database is reachable."""
        database: Database | None = app.state.db
        if database is None:
            raise HTTPException(status_code=503, detail="database not configured")
        try:
            async with database.session() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("readiness_check_failed", error=str(exc))
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return ReadyResponse()

    if bot_app is not None or settings.telegram_bot_token:
        register_webhook(app, settings=settings)

    return app
