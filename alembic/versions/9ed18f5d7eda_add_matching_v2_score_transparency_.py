"""add matching v2 score transparency columns to job_matches

Revision ID: 9ed18f5d7eda
Revises: f89b984f2790
Create Date: 2026-09-05 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '9ed18f5d7eda'
down_revision: str | None = 'f89b984f2790'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Matching Engine V2 (forensic false-positive audit, item G — "numeric
    # score must agree with decision"): the pre-cap weighted-average score
    # (`raw_fit_score`) alongside the strong-negative-signal flags
    # (`risk_flags`) that can cap the displayed `overall_score` below it.
    # Both nullable: existing rows get NULL until the next matching run
    # recomputes them (job_agent.matching.cache.MATCH_LOGIC_VERSION was
    # bumped specifically to force that recompute) — never backfilled by
    # this migration, since a plausible-looking guess at a HISTORICAL raw
    # score would be fabricated data, not a real recomputation.
    op.add_column('job_matches', sa.Column('raw_fit_score', sa.Float(), nullable=True))
    op.add_column('job_matches', sa.Column('risk_flags', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_matches', 'risk_flags')
    op.drop_column('job_matches', 'raw_fit_score')
