"""Security primitives.

Currently: constant-time verification of the Telegram webhook secret token. Kept
here (not inline in the route) so the comparison is unit-testable in isolation and
reused wherever a secret must be checked.
"""

from __future__ import annotations

import hmac


def constant_time_compare(provided: str | None, expected: str | None) -> bool:
    """Compare two secrets in constant time.

    Returns ``False`` (never raises) when either value is missing, so an unset
    server secret or an absent request header can never be coerced into a match.
    Uses :func:`hmac.compare_digest`, which does not short-circuit on the first
    differing byte — defeating timing attacks that a plain ``==`` would leak.
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def verify_webhook_token(provided: str | None, expected: str | None) -> bool:
    """True iff the request's ``X-Telegram-Bot-Api-Secret-Token`` matches config.

    A thin, intention-revealing alias over :func:`constant_time_compare` for the
    webhook route's authorization check.
    """
    return constant_time_compare(provided, expected)
