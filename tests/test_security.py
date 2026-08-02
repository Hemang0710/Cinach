"""Constant-time webhook-token verification."""

from __future__ import annotations

import pytest

from cinch.core.security import constant_time_compare, verify_webhook_token


def test_matching_tokens_pass() -> None:
    assert constant_time_compare("s3cret", "s3cret") is True
    assert verify_webhook_token("s3cret", "s3cret") is True


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        ("wrong", "s3cret"),  # mismatch
        (None, "s3cret"),  # header absent
        ("s3cret", None),  # server secret unset
        (None, None),  # both absent
        ("", "s3cret"),  # empty header
        ("s3cre", "s3cret"),  # differing length
    ],
)
def test_non_matching_tokens_fail(provided: str | None, expected: str | None) -> None:
    assert constant_time_compare(provided, expected) is False
    assert verify_webhook_token(provided, expected) is False
