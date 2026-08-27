"""Cross-source duplicate detection for applications.

The per-(job_id, candidate_id) uniqueness in `applications.repository` /
the DB schema stops a duplicate row for the *same* Job record. It cannot
stop two *different* Job rows that are actually the same underlying
posting (e.g. discovered via both a company's Greenhouse board and its own
careers page) from each getting their own Application — that's exactly
what `job_agent.jobs.fingerprint.compute_job_fingerprint` exists to detect,
and this module is where the application engine acts on it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from job_agent.applications.repository import get_application
from job_agent.db.models import Application
from job_agent.db.models import Job as JobRow
from job_agent.jobs.repository import find_by_fingerprint


def find_cross_source_duplicate_application(
    session: Session, job: JobRow, candidate_id: int
) -> Application | None:
    """An existing Application for a *different* Job row sharing this
    job's content fingerprint, if one exists — meaning this posting has
    already been (or is already being) applied to under another source."""
    for other_job in find_by_fingerprint(session, job.job_fingerprint):
        if other_job.id == job.id:
            continue
        existing = get_application(session, other_job.id, candidate_id)
        if existing is not None:
            return existing
    return None
