"""submission fields on applications

Adds the Phase 6 assisted-submission outcome columns to ``applications``:
``submitted_at`` (when a submit attempt completed) and ``submission_detail``
(a short, PII-free note — handoff URL, skip reason, or error summary).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-02 13:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("submission_detail", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_column("submission_detail")
        batch_op.drop_column("submitted_at")
