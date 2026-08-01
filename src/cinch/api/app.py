"""FastAPI application factory.

Phase 0 exposes only liveness/readiness probes. The Telegram webhook route and
its secret-token verification are added in Phase 3.
"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from cinch import __version__
from cinch.core.config import Settings, get_settings
from cinch.core.logging import configure_logging


class HealthResponse(BaseModel):
    """Response body for the liveness probe."""

    status: Literal["ok"] = "ok"
    version: str


class ReadyResponse(BaseModel):
    """Response body for the readiness probe."""

    status: Literal["ready"] = "ready"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        settings: Optional settings override (dependency injection for tests).
            Falls back to the cached environment-derived settings.
    """
    settings = settings or get_settings()
    configure_logging(log_level=settings.log_level, json_logs=settings.log_json)

    app = FastAPI(
        title="Cinch",
        version=__version__,
        summary="Human-in-the-loop job application assistant.",
    )

    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        """Liveness probe: the process is up and serving requests."""
        return HealthResponse(version=__version__)

    @app.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        """Readiness probe: the app is ready to accept traffic.

        Phase 0 has no external dependencies to check. Later phases will verify
        the database connection and other dependencies here.
        """
        return ReadyResponse()

    return app
