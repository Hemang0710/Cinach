"""Structured logging setup using structlog.

Emits JSON logs in production (machine-parseable, PII-redaction friendly) and
human-readable console logs locally. Call :func:`configure_logging` once at
application startup.
"""

from __future__ import annotations

import logging

import structlog
from structlog.typing import EventDict, WrappedLogger

# Keys that must never appear verbatim in logs (secrets + PII). Matched case-insensitively.
_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "secret",
        "secret_token",
        "password",
        "authorization",
        "api_key",
        "apikey",
        "anthropic_api_key",
        "openai_api_key",
        "google_api_key",
        "adzuna_app_key",
        "telegram_bot_token",
        "telegram_webhook_secret",
        "encryption_key",
        "sentry_dsn",
        "content",
        "resume",
    }
)


def _redact_sensitive(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Mask any sensitive keys so a stray secret/PII kwarg never lands in a log line."""
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***"
    return event_dict


def configure_logging(*, log_level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structlog + stdlib logging.

    Args:
        log_level: Minimum level name (e.g. ``"INFO"``, ``"DEBUG"``).
        json_logs: Render logs as JSON when True, otherwise a colorised console
            renderer for local development.
    """
    level = logging.getLevelName(log_level.upper())
    if not isinstance(level, int):  # pragma: no cover - defensive
        level = logging.INFO

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_sensitive,
    ]

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
