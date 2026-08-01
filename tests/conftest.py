"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cinch.api.app import create_app
from cinch.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Deterministic test settings (no reliance on the ambient environment)."""
    return Settings(environment="local", log_json=False)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An httpx AsyncClient wired to the ASGI app in-process (no network)."""
    app = create_app(settings=settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
