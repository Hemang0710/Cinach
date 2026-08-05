"""Sentry initialisation is opt-in (DSN-gated) and PII-safe."""

from __future__ import annotations

from unittest.mock import patch

from cinch.core.config import Settings
from cinch.core.observability import init_sentry


def test_init_sentry_is_noop_without_dsn() -> None:
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(Settings(_env_file=None, sentry_dsn=None))
    mock_init.assert_not_called()


def test_init_sentry_initialises_with_dsn() -> None:
    settings = Settings(_env_file=None, sentry_dsn="https://public@o0.ingest.sentry.io/1")
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(settings)
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["send_default_pii"] is False  # PII-safe by construction


def test_init_sentry_survives_bad_dsn() -> None:
    # A malformed DSN must warn and continue, never crash the app at startup.
    init_sentry(Settings(_env_file=None, sentry_dsn="not-a-valid-dsn"))
