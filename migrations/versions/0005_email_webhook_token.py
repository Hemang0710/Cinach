"""per-user email webhook token on users

Adds the Phase 14 ``email_webhook_token`` column to ``users`` — a unique,
indexed, nullable token the inbound-email webhook resolves to a user (replacing
the single-owner ``_pick_user``). Nullable because existing users have no token
until they run ``/emailhook``. The new GHOSTED status and allowlist config need
no migration (status is already ``String(32)``; the allowlist is env-only).

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email_webhook_token", sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_users_email_webhook_token"),
            ["email_webhook_token"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email_webhook_token"))
        batch_op.drop_column("email_webhook_token")
