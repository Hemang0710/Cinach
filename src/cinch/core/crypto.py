"""Application-level encryption for PII at rest (Fernet).

Resume content is the sensitive payload. When ``ENCRYPTION_KEY`` is set, values are
encrypted before they reach the database and decrypted on read; when it is unset,
values pass through as plaintext (a one-time startup warning is logged) so local
development works without key management.

The key is read from the environment fresh on each call rather than cached, so the
column type picks up whatever the process was started with (and tests can
``monkeypatch.setenv``). Constructing a ``Fernet`` is cheap relative to a DB round-trip.
"""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from cinch.core.logging import get_logger

logger = get_logger(__name__)

_warned_plaintext = False


class InvalidEncryptionKeyError(RuntimeError):
    """Raised when ``ENCRYPTION_KEY`` is set but is not a valid Fernet key."""


def cipher_from_env() -> Fernet | None:
    """Return a ``Fernet`` built from ``ENCRYPTION_KEY``, or ``None`` if unset.

    Logs a one-time warning when no key is configured (PII stored plaintext).
    """
    global _warned_plaintext
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        if not _warned_plaintext:
            logger.warning("encryption_key_unset_plaintext_pii")
            _warned_plaintext = True
        return None
    return Fernet(key.encode())


def validate_encryption_key(key: str | None) -> None:
    """Fail fast at startup if ``ENCRYPTION_KEY`` is set but malformed.

    Without this, a bad key only surfaces on the first DB write (from deep inside a
    SQLAlchemy INSERT) — the user sees no error and nothing is saved. Catching it at
    startup makes the deploy fail visibly with a clear, actionable message.
    """
    if not key:
        return
    try:
        Fernet(key.encode())
    except ValueError as exc:
        raise InvalidEncryptionKeyError(
            "ENCRYPTION_KEY is not a valid Fernet key "
            "(must be 32 url-safe base64-encoded bytes; usually 44 chars ending in '='). "
            "Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from exc


def encrypt_json(data: dict[str, object], cipher: Fernet | None) -> str | dict[str, object]:
    """Encrypt ``data`` to a ciphertext string, or return it unchanged if no cipher."""
    if cipher is None:
        return data
    return cipher.encrypt(json.dumps(data).encode()).decode()


def decrypt_json(value: str | dict[str, object], cipher: Fernet | None) -> dict[str, object]:
    """Decrypt a stored value back to a dict.

    Handles all four combinations of (value is plaintext dict / ciphertext string)
    and (cipher present / absent):

    - ``dict`` → already plaintext, returned as-is (works with or without a cipher).
    - ``str`` + cipher → decrypted; if the token is invalid it is treated as a legacy
      plaintext JSON string (a row written before a key existed).
    - ``str`` + no cipher → a legacy plaintext JSON string is parsed; genuine
      ciphertext without a key cannot be read and raises.
    """
    if isinstance(value, dict):
        return value
    if cipher is not None:
        try:
            return json.loads(cipher.decrypt(value.encode()))  # type: ignore[no-any-return]
        except InvalidToken:
            return json.loads(value)  # type: ignore[no-any-return]
    return json.loads(value)  # type: ignore[no-any-return]
