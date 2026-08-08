"""email-tracking columns on applications

Adds Phase 11 email-tracking columns to ``applications``: ``last_email_at`` (when
the most recent classified email arrived) and ``last_email_summary`` (a short,
PII-lean LLM-produced note for dashboard display). New status enum values
(INTERVIEW_INVITED, INTERVIEW_SCHEDULED, OFFERED, ACCEPTED, REJECTED) don't need
a migration — the status column is already ``String(32)`` and existing rows are
untouched by the new values.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-07 20:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_email_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_email_summary", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_column("last_email_summary")
        batch_op.drop_column("last_email_at")
