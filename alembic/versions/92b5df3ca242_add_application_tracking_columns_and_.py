"""add application tracking columns and job/candidate uniqueness

Revision ID: 92b5df3ca242
Revises: e60a4fbe27a2
Create Date: 2026-08-27 07:48:22.044019

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '92b5df3ca242'
down_revision: str | None = 'e60a4fbe27a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite has no ALTER-of-constraints support — adding the unique
    # constraint and foreign key requires batch mode (copy-and-move), per
    # https://alembic.sqlalchemy.org/en/latest/batch.html. Plain column
    # adds don't strictly need it, but keeping the whole table's changes
    # in one batch block keeps this migration simple and correct.
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile_version_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.create_unique_constraint(
            "uq_applications_job_candidate", ["job_id", "candidate_id"]
        )
        batch_op.create_foreign_key(
            "fk_applications_profile_version_id",
            "candidate_profile_versions",
            ["profile_version_id"],
            ["id"],
        )

    with op.batch_alter_table("application_answers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("validated", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("validation_notes", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("application_answers", schema=None) as batch_op:
        batch_op.drop_column("validation_notes")
        batch_op.drop_column("validated")

    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_constraint("fk_applications_profile_version_id", type_="foreignkey")
        batch_op.drop_constraint("uq_applications_job_candidate", type_="unique")
        batch_op.drop_column("dry_run")
        batch_op.drop_column("profile_version_id")
