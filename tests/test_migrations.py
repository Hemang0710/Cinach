"""Migration tests: the Alembic migration applies cleanly and matches the models.

These are **sync** tests: Alembic's async ``env.py`` runs its own event loop, so we
must not be inside one when calling ``command.upgrade``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from cinch.core.config import get_settings
from cinch.db.base import Base
from cinch.db.models import ApplicationORM, JobORM, ResumeORM, UserORM

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Deriving from the ORM classes both registers their tables on Base.metadata and
# keeps this set in lock-step with the models.
EXPECTED_TABLES = {
    UserORM.__tablename__,
    ResumeORM.__tablename__,
    JobORM.__tablename__,
    ApplicationORM.__tablename__,
}


@pytest.fixture
def migrated_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Apply ``alembic upgrade head`` to a throwaway SQLite DB; yield its URL.

    ``env.py`` reads the URL from settings, so we point ``DATABASE_URL`` at the
    temp file and clear the cached settings before/after.
    """
    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/m.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    try:
        yield url
    finally:
        get_settings.cache_clear()


def test_upgrade_creates_all_tables(migrated_url: str) -> None:
    sync_engine = create_engine(migrated_url.replace("+aiosqlite", ""))
    try:
        tables = set(inspect(sync_engine).get_table_names())
    finally:
        sync_engine.dispose()
    assert tables >= EXPECTED_TABLES
    assert "alembic_version" in tables


def test_migration_matches_models_no_structural_drift(migrated_url: str) -> None:
    """The migrated schema has no structural drift from ``Base.metadata``.

    Guards against a model change that was never captured in a migration. Type
    comparison is disabled because SQLite reflects ``Uuid`` as ``CHAR`` and would
    otherwise report false positives; added/removed tables, columns, indexes, and
    constraints are still detected.
    """
    sync_engine = create_engine(migrated_url.replace("+aiosqlite", ""))
    try:
        with sync_engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": False, "target_metadata": Base.metadata}
            )
            diffs = compare_metadata(ctx, Base.metadata)
    finally:
        sync_engine.dispose()
    assert diffs == [], f"Uncaptured schema drift: {diffs}"


def test_user_telegram_ids_are_bigint() -> None:
    """Telegram ids are 64-bit; 32-bit Integer overflows on PostgreSQL (see migration 0003)."""
    from sqlalchemy import BigInteger

    assert isinstance(UserORM.__table__.c.telegram_user_id.type, BigInteger)
    assert isinstance(UserORM.__table__.c.telegram_chat_id.type, BigInteger)
