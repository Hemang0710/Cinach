"""Structured-logging redaction of sensitive keys."""

from __future__ import annotations

from cinch.core.logging import _redact_sensitive


def test_redacts_sensitive_keys_only() -> None:
    event = {
        "event": "resume_saved",
        "token": "abc",
        "api_key": "k",
        "content": {"summary": "PII"},
        "telegram_user_id": 5,  # non-sensitive identifier
    }
    out = _redact_sensitive(None, "info", dict(event))

    assert out["token"] == "***"
    assert out["api_key"] == "***"
    assert out["content"] == "***"
    assert out["telegram_user_id"] == 5  # untouched
    assert out["event"] == "resume_saved"


def test_redaction_is_case_insensitive() -> None:
    out = _redact_sensitive(None, "info", {"Authorization": "Bearer x", "Secret": "y"})
    assert out["Authorization"] == "***"
    assert out["Secret"] == "***"
