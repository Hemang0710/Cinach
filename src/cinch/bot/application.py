"""Construct the python-telegram-bot ``Application``.

The bot is built per-process and **injected** (its ``Database`` lives in ``bot_data``,
not a module global). ``AIORateLimiter`` enforces Telegram's send limits (~1 msg/s per
chat, ~30/s global) and retries on 429 automatically, so handlers never hand-roll
backoff. ``/demo`` is registered only outside production.
"""

from __future__ import annotations

from typing import Any

from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from cinch.bot.handlers import (
    callback_handler,
    demo_command,
    discover_command,
    document_handler,
    setresume_command,
    start_command,
)
from cinch.core.config import Settings
from cinch.db.session import Database

# PTB's Application is generic over six type params; we don't specialize them here.
BotApp = Application[Any, Any, Any, Any, Any, Any]


def build_bot_application(settings: Settings, db: Database) -> BotApp:
    """Build a configured PTB ``Application`` (handlers + rate limiter + injected db)."""
    if not settings.telegram_bot_token:
        raise ValueError("telegram_bot_token is required to build the bot application")

    app: BotApp = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .rate_limiter(AIORateLimiter())
        .build()
    )
    app.bot_data["db"] = db
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("setresume", setresume_command))
    app.add_handler(CommandHandler("discover", discover_command))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    if not settings.is_production:
        app.add_handler(CommandHandler("demo", demo_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    return app
