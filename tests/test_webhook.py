"""Webhook authentication + dispatch.

The PTB application is injected as a fake (async ``process_update``), so no bot token,
network, or lifespan run is required — the route reads ``app.state.bot_app`` directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from cinch.api.app import create_app
from cinch.core.config import Settings

SECRET = "s3cret-token"
HEADER = "X-Telegram-Bot-Api-Secret-Token"


@pytest.fixture
def bot_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="local",
        log_json=False,
        telegram_bot_token="123:abc",
        telegram_webhook_secret=SECRET,
    )


@pytest.fixture
def fake_bot_app() -> SimpleNamespace:
    return SimpleNamespace(bot=MagicMock(), process_update=AsyncMock())


@pytest.fixture
async def client(
    bot_settings: Settings, fake_bot_app: SimpleNamespace
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings=bot_settings, bot_app=fake_bot_app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def test_wrong_secret_is_forbidden(
    client: AsyncClient, bot_settings: Settings, fake_bot_app: SimpleNamespace
) -> None:
    resp = await client.post(
        bot_settings.telegram_webhook_path,
        json={"update_id": 1},
        headers={HEADER: "wrong"},
    )
    assert resp.status_code == 403
    fake_bot_app.process_update.assert_not_called()


async def test_missing_secret_is_forbidden(
    client: AsyncClient, bot_settings: Settings, fake_bot_app: SimpleNamespace
) -> None:
    resp = await client.post(bot_settings.telegram_webhook_path, json={"update_id": 1})
    assert resp.status_code == 403
    fake_bot_app.process_update.assert_not_called()


async def test_valid_secret_dispatches_update(
    client: AsyncClient, bot_settings: Settings, fake_bot_app: SimpleNamespace
) -> None:
    resp = await client.post(
        bot_settings.telegram_webhook_path,
        json={"update_id": 1},
        headers={HEADER: SECRET},
    )
    assert resp.status_code == 200
    fake_bot_app.process_update.assert_awaited_once()
