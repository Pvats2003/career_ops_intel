"""phase 16 cost control: job_matches.cache_key

Revision ID: b79d72e2866c
Revises: cf8ed6778bde
Create Date: 2026-09-03 10:59:39.427454

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b79d72e2866c'
down_revision: str | None = 'cf8ed6778bde'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('job_matches', sa.Column('cache_key', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_job_matches_cache_key'), 'job_matches', ['cache_key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_job_matches_cache_key'), table_name='job_matches')
    op.drop_column('job_matches', 'cache_key')
