"""FastAPI application factory.

Exposes health probes and, when a Telegram bot token is configured, the
secret-token-verified webhook. A ``lifespan`` owns the async ``Database`` and the
PTB ``Application`` it creates (initialize/start on boot, stop/dispose on shutdown);
tests inject their own ``db``/``bot_app`` instead, which the factory places on
``app.state`` immediately so no live bot or lifespan run is required.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel

from cinch import __version__
from cinch.api.webhook import register_webhook
from cinch.bot.application import build_bot_application
from cinch.core.config import Settings, get_settings
from cinch.core.logging import configure_logging
from cinch.db.session import Database


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
        try:
            yield
        finally:
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

    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        """Liveness probe: the process is up and serving requests."""
        return HealthResponse(version=__version__)

    @app.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        """Readiness probe: the app is ready to accept traffic."""
        return ReadyResponse()

    if bot_app is not None or settings.telegram_bot_token:
        register_webhook(app, settings=settings)

    return app
