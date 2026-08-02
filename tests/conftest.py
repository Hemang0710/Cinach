"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cinch.api.app import create_app
from cinch.core.config import Settings
from cinch.db.session import Database


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


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    """A throwaway SQLite database with the schema created from metadata.

    A file under ``tmp_path`` (not ``:memory:``) so the schema persists across the
    separate connections a repository may open within one test.
    """
    database = Database(f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    """An open session against the throwaway database (commits on exit)."""
    async with db.session() as sess:
        yield sess
