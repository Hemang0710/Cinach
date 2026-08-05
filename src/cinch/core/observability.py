"""Error monitoring (Sentry) wiring.

``init_sentry`` is a no-op unless ``SENTRY_DSN`` is configured, so dev and tests never
initialise Sentry. When enabled it runs PII-safe: ``send_default_pii=False`` plus a
``before_send`` hook that strips request bodies/headers, so resume content and secrets
are never shipped to the error backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cinch.core.config import Settings
from cinch.core.logging import get_logger

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

logger = get_logger(__name__)


def _scrub(event: Event, hint: Hint) -> Event | None:
    """Drop request payload/headers from events as defence-in-depth against PII leaks."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("headers", None)
    return event


def init_sentry(settings: Settings) -> None:
    """Initialise Sentry if a DSN is configured; otherwise do nothing."""
    if not settings.sentry_dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            send_default_pii=False,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            before_send=_scrub,
            integrations=[StarletteIntegration(), FastApiIntegration()],
        )
    except Exception as exc:
        # A misconfigured DSN must never take the whole service down — Sentry is optional.
        logger.warning("sentry_init_failed", error=str(exc))
        return
    logger.info("sentry_initialised", environment=settings.environment)
