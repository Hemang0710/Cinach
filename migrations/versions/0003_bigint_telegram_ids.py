"""widen telegram ids to BigInteger

Telegram user/chat ids are 64-bit and can exceed PostgreSQL's 32-bit INTEGER
(e.g. 6984602416), which raised ``DataError: value out of int32 range`` on /start.
Widen both ``users`` id columns to BIGINT. SQLite's INTEGER is already dynamically
64-bit, so the change is a no-op there (and it cannot ALTER COLUMN TYPE anyway).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04 08:15:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite INTEGER already stores 64-bit values
    op.alter_column(
        "users",
        "telegram_user_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "telegram_chat_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "users",
        "telegram_user_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "telegram_chat_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=False,
    )
