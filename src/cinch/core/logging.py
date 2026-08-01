"""Structured logging setup using structlog.

Emits JSON logs in production (machine-parseable, PII-redaction friendly) and
human-readable console logs locally. Call :func:`configure_logging` once at
application startup.
"""

from __future__ import annotations

import logging

import structlog


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
