"""add application checklist columns

Revision ID: e14425c321b6
Revises: b79d72e2866c
Create Date: 2026-09-04 08:41:52.315139

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e14425c321b6'
down_revision: str | None = 'b79d72e2866c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default='0' on these NOT NULL columns: SQLite requires a
    # DEFAULT for a NOT-NULL column added via ALTER TABLE, and it also
    # backfills every pre-existing application to "not yet checked off" —
    # the same default the model's Python side already uses for new rows.
    op.add_column(
        'applications',
        sa.Column('cover_letter_ready', sa.Boolean(), nullable=False, server_default='0'),
    )
    op.add_column(
        'applications',
        sa.Column('questions_prepared', sa.Boolean(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('applications', 'questions_prepared')
    op.drop_column('applications', 'cover_letter_ready')
