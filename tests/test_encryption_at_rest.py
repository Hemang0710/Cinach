"""Proves resume PII is encrypted at the database row level when a key is set."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from cinch.db.repositories import ResumeRepository, UserRepository
from cinch.db.session import Database

CONTENT: dict[str, object] = {"summary": "Secret Engineer", "skills": ["Python"]}


async def _raw_content(db: Database) -> str:
    """Read the stored content column bypassing the ORM's decrypting type."""
    async with db.session() as session:
        result = await session.execute(text("SELECT content FROM resumes"))
        return str(result.scalar_one())


async def test_content_is_ciphertext_at_rest_with_key(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(1, 2)
        await ResumeRepository(session).set_master(user.id, CONTENT)

    stored = await _raw_content(db)
    assert "Secret Engineer" not in stored  # encrypted at rest

    # ...but reads transparently decrypt back to the original dict.
    async with db.session() as session:
        fetched = await UserRepository(session).get_by_telegram_id(1)
        assert fetched is not None
        master = await ResumeRepository(session).get_master(fetched.id)
    assert master is not None
    assert master.content == CONTENT


async def test_content_is_plaintext_without_key(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(3, 4)
        await ResumeRepository(session).set_master(user.id, {"summary": "Plain"})

    stored = await _raw_content(db)
    assert "Plain" in stored  # plaintext fallback (no key configured)
