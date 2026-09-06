"""add performance indexes to jobs and job_matches

Revision ID: f89b984f2790
Revises: 1ff2d5b799c0
Create Date: 2026-09-04 10:31:58.106424

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f89b984f2790"
down_revision: str | None = "1ff2d5b799c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_job_matches_job_candidate_created",
        "job_matches",
        ["job_id", "candidate_id", "created_at"],
    )
    op.create_index("ix_jobs_lifecycle_status", "jobs", ["lifecycle_status"])
    op.create_index("ix_jobs_source_id", "jobs", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_source_id", table_name="jobs")
    op.drop_index("ix_jobs_lifecycle_status", table_name="jobs")
    op.drop_index("ix_job_matches_job_candidate_created", table_name="job_matches")
