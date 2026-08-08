"""Magic-link + session signing for the dashboard (Phase 10).

Uses **stdlib only** (``hmac`` + ``hashlib`` + ``secrets``) so there's no new dep.
Two token types with different expiries share the same wire format and secret:

- **Magic-link token** (short, ~10 min): issued by ``/dashboard`` in the bot,
  consumed by ``GET /dashboard/login`` which sets the session cookie.
- **Session token** (long, ~7 days): stored in an HttpOnly cookie, checked on
  every dashboard request.

The signing key is **derived** from ``TELEGRAM_WEBHOOK_SECRET`` — a value the
service already requires — so the dashboard survives restarts without a new env
var. Constant-time comparison guards against timing attacks on the HMAC check.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Final
from uuid import UUID

MAGIC_LINK_TTL_SECONDS: Final = 10 * 60
SESSION_TTL_SECONDS: Final = 7 * 24 * 3600
_SIG_LEN: Final = 32  # HMAC-SHA256 truncated to 32 bytes


class InvalidTokenError(Exception):
    """Raised when a token's signature fails, it's expired, or it's malformed."""


@dataclass(frozen=True)
class TokenPayload:
    """A verified token payload — just the user id and its (unix) expiry."""

    user_id: UUID
    expires_at: int  # unix timestamp (seconds)


def _key(webhook_secret: str) -> bytes:
    """Derive a dashboard-specific signing key from the (required) webhook secret.

    A distinct purpose string means a leaked webhook secret alone can't forge
    dashboard tokens without also knowing the derivation constant (defence in depth).
    """
    return hashlib.sha256(f"cinch-dashboard-v1::{webhook_secret}".encode()).digest()


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding — safe for both URL params and cookies."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    """Inverse of :func:`_b64url`. Raises ``ValueError`` on garbled input."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_token(user_id: UUID, ttl_seconds: int, webhook_secret: str) -> str:
    """Sign ``{user_id, exp}`` and return the ``"<payload>.<sig>"`` string."""
    payload_json = json.dumps({"uid": str(user_id), "exp": int(time.time()) + ttl_seconds})
    payload = _b64url(payload_json.encode())
    sig = _b64url(hmac.new(_key(webhook_secret), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str, webhook_secret: str, *, now: int | None = None) -> TokenPayload:
    """Verify signature + expiry; return the payload or raise :class:`InvalidTokenError`."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise InvalidTokenError("malformed token") from exc

    expected = hmac.new(_key(webhook_secret), payload_b64.encode(), hashlib.sha256).digest()
    try:
        actual = _b64url_decode(sig_b64)
    except ValueError as exc:
        raise InvalidTokenError("bad signature encoding") from exc
    if len(actual) != _SIG_LEN or not hmac.compare_digest(expected, actual):
        raise InvalidTokenError("signature mismatch")

    try:
        data = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("bad payload encoding") from exc

    try:
        uid = UUID(data["uid"])
        exp = int(data["exp"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError("payload missing/invalid fields") from exc

    if exp < (now if now is not None else int(time.time())):
        raise InvalidTokenError("token expired")
    return TokenPayload(user_id=uid, expires_at=exp)
