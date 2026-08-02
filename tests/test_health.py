"""Smoke tests for the health endpoints.

These prove the FastAPI app, the async test harness, and the CI toolchain
(ruff/mypy/pytest) all work end-to-end.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from cinch import __version__
from cinch.api.app import create_app
from cinch.core.config import Settings


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


async def test_readyz_returns_ready_when_db_healthy(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


async def test_readyz_returns_503_without_db() -> None:
    # No db injected and the lifespan doesn't run under ASGITransport → not ready.
    app = create_app(settings=Settings(_env_file=None))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get("/readyz")
    assert resp.status_code == 503


async def test_response_carries_request_id(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.headers.get("X-Request-ID")
