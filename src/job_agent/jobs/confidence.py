"""Data confidence — deliberately separate from match score (Career OS
FINAL GOD MODE Part 3.8).

A job can score 91/100 on fit and still be built on shaky data: no salary
listed, no verifiable posting date, no company link, no direct application
URL. Reporting a crisp "91" next to a job like that is false precision —
the candidate reads it as "we know this is a 91", when really the match
itself is solid but several of the underlying facts are unconfirmed. This
module scores confidence in the DATA, not in the match, from whatever the
source actually gave us — never inferred or guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from job_agent.db.models import Job as JobRow
from job_agent.jobs.schema import FreshnessStatus

ConfidenceLevel = Literal["High", "Medium"]


@dataclass(frozen=True)
class DataConfidence:
    level: ConfidenceLevel
    reasons: list[str]


def assess_data_confidence(job: JobRow) -> DataConfidence:
    reasons: list[str] = []

    if job.salary_min is None and job.salary_max is None:
        reasons.append("Salary not listed by the source")

    if job.posted_at is None or job.freshness_status == FreshnessStatus.UNKNOWN_POST_DATE.value:
        reasons.append("Posting date could not be verified")

    if not job.company_url and job.company_id is None:
        reasons.append("Company details limited (no company page or profile)")

    if not job.application_url:
        reasons.append("No direct application URL")

    level: ConfidenceLevel = "Medium" if reasons else "High"
    return DataConfidence(level=level, reasons=reasons)
