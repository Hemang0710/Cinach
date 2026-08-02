"""Custom SQLAlchemy column types.

``EncryptedJSON`` transparently encrypts a JSON payload (resume PII) at rest. Its
``impl`` stays :class:`~sqlalchemy.JSON`, so the emitted DDL is identical to a plain
JSON column — **no migration is required** and ciphertext is stored as a JSON string
while plaintext (no key configured) is stored as a JSON object.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import JSON
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

from cinch.core.crypto import cipher_from_env, decrypt_json, encrypt_json


class EncryptedJSON(TypeDecorator[dict[str, object]]):
    """A JSON column whose value is Fernet-encrypted when ``ENCRYPTION_KEY`` is set."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: dict[str, object] | None, dialect: Dialect) -> object:
        """Encrypt on write (ciphertext string), or store the dict when no key is set."""
        if value is None:
            return None
        return encrypt_json(value, cipher_from_env())

    def process_result_value(
        self, value: object | None, dialect: Dialect
    ) -> dict[str, object] | None:
        """Decrypt on read; a plaintext dict passes straight through."""
        if value is None:
            return None
        return decrypt_json(cast("str | dict[str, object]", value), cipher_from_env())
