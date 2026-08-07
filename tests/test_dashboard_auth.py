"""Dashboard token signing + verification (Phase 10)."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from cinch.api.dashboard.auth import (
    InvalidTokenError,
    sign_token,
    verify_token,
)

_SECRET = "unit-test-webhook-secret-value"


def test_roundtrip_returns_payload() -> None:
    uid = uuid4()
    token = sign_token(uid, ttl_seconds=60, webhook_secret=_SECRET)
    payload = verify_token(token, _SECRET)
    assert payload.user_id == uid
    assert payload.expires_at > int(time.time())


def test_expired_token_is_rejected() -> None:
    uid = uuid4()
    token = sign_token(uid, ttl_seconds=1, webhook_secret=_SECRET)
    with pytest.raises(InvalidTokenError, match="expired"):
        verify_token(token, _SECRET, now=int(time.time()) + 10)


def test_signature_tampered_rejected() -> None:
    token = sign_token(uuid4(), ttl_seconds=60, webhook_secret=_SECRET)
    payload_b64, _ = token.split(".")
    # Reattach a valid-shape but wrong signature.
    forged = payload_b64 + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_token(forged, _SECRET)


def test_payload_tampered_rejected() -> None:
    """Changing the payload after signing must invalidate the token."""
    token = sign_token(uuid4(), ttl_seconds=60, webhook_secret=_SECRET)
    _, sig = token.split(".")
    # Different (well-formed) payload with the original signature.
    other = sign_token(uuid4(), ttl_seconds=60, webhook_secret=_SECRET)
    other_payload, _ = other.split(".")
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_token(f"{other_payload}.{sig}", _SECRET)


def test_wrong_secret_rejected() -> None:
    token = sign_token(uuid4(), ttl_seconds=60, webhook_secret=_SECRET)
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_token(token, "different-secret")


def test_malformed_token_rejected() -> None:
    for bad in ("no-dot-here", "a.b.c", "!!!.^^^^", ""):
        with pytest.raises(InvalidTokenError):
            verify_token(bad, _SECRET)
