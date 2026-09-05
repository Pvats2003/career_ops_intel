"""add candidate profile fingerprint column

Revision ID: 7d33c8ef72b2
Revises: 9ed18f5d7eda
Create Date: 2026-09-05 20:41:15.243104

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '7d33c8ef72b2'
down_revision: str | None = '9ed18f5d7eda'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Dashboard performance forensic fix — `save_candidate_profile()` used
    # to unconditionally delete and reinsert every fact/skill/experience/
    # project row on every single request (any endpoint depending on
    # `CandidateDep`, i.e. nearly the whole API), because it had no way to
    # tell "the parsed profile is identical to what's already stored"
    # across separate requests/processes. `profile_fingerprint` stores
    # `job_agent.resume.versioning.compute_profile_hash()`'s sha256 of the
    # profile's semantic content (excluding `parsed_at`), so a future
    # request can skip the whole delete/reinsert cycle when nothing
    # changed. Nullable: existing rows get NULL, which the read path
    # treats as "unknown, must resync" — a one-time resync per existing
    # candidate on the first request after this migration, never a
    # fabricated/backfilled value.
    op.add_column(
        'candidate', sa.Column('profile_fingerprint', sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('candidate', 'profile_fingerprint')
