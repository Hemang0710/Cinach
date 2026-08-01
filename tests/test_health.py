"""Smoke tests for the health endpoints.

These prove the FastAPI app, the async test harness, and the CI toolchain
(ruff/mypy/pytest) all work end-to-end.
"""

from __future__ import annotations

from httpx import AsyncClient

from cinch import __version__


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


async def test_readyz_returns_ready(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
