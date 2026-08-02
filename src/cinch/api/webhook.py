"""Telegram webhook route.

Security-critical entry point. Every request is authenticated by a constant-time
comparison of the ``X-Telegram-Bot-Api-Secret-Token`` header against the configured
secret **before the body is read or parsed** — a mismatch returns 403 and nothing
else happens. Valid updates are handed to the PTB ``Application`` for routing.

A handler error returns 200 (logged, not raised) so Telegram does not enter a retry
storm; only an authentication failure returns a non-2xx status.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, Request, Response
from telegram import Update

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.core.security import verify_webhook_token

logger = get_logger(__name__)


def register_webhook(app: FastAPI, *, settings: Settings) -> None:
    """Register ``POST {telegram_webhook_path}`` on the FastAPI app.

    The PTB application is read from ``app.state.bot_app`` at request time (set by
    the lifespan or injected in tests), so this route works regardless of when the
    bot is constructed.
    """

    @app.post(settings.telegram_webhook_path, include_in_schema=False)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> Response:
        if not verify_webhook_token(
            x_telegram_bot_api_secret_token, settings.telegram_webhook_secret
        ):
            return Response(status_code=403)

        bot_app = getattr(request.app.state, "bot_app", None)
        if bot_app is None:  # bot not configured on this instance
            return Response(status_code=503)

        update = Update.de_json(await request.json(), bot_app.bot)
        try:
            await bot_app.process_update(update)
        except Exception:
            logger.exception("webhook_update_failed")
        return Response(status_code=200)
