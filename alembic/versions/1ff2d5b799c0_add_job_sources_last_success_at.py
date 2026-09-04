"""add job_sources last_success_at

Revision ID: 1ff2d5b799c0
Revises: e14425c321b6
Create Date: 2026-09-04 09:19:39.478245

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '1ff2d5b799c0'
down_revision: str | None = 'e14425c321b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'job_sources', sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('job_sources', 'last_success_at')
