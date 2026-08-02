"""Fernet JSON encryption helpers + plaintext fallback."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from cinch.core.crypto import cipher_from_env, decrypt_json, encrypt_json


def test_roundtrip_with_key() -> None:
    cipher = Fernet(Fernet.generate_key())
    data: dict[str, object] = {"summary": "Engineer", "skills": ["Python"]}
    token = encrypt_json(data, cipher)
    assert isinstance(token, str)
    assert "Engineer" not in token  # ciphertext, not plaintext
    assert decrypt_json(token, cipher) == data


def test_plaintext_passthrough_without_key() -> None:
    data: dict[str, object] = {"a": 1}
    assert encrypt_json(data, None) == data  # dict stored as-is
    assert decrypt_json(data, None) == data  # dict read as-is


def test_legacy_plaintext_string_decodes_with_key() -> None:
    # A row written before a key existed (plaintext JSON string) still decodes.
    cipher = Fernet(Fernet.generate_key())
    assert decrypt_json('{"a": 1}', cipher) == {"a": 1}


def test_cipher_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    assert cipher_from_env() is None
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert cipher_from_env() is not None
