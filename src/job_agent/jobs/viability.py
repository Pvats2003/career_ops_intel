"""Application viability — Career OS FINAL GOD MODE Part 3.9.

A high match score doesn't mean applying is actually straightforward. This
assesses the practical, mechanical questions a candidate asks before
spending 20 minutes on an application: is there a URL, is the job still
listed as open, are the qualifications roughly there, is the location
workable, is visa/sponsorship information even available. Everything here
is read from data the pipeline already stored — nothing is a live network
check (see `job_agent.jobs.url_check` for the one thing that is, kept
separate and on-demand because it costs a real outbound request).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch

OverallViability = Literal["VIABLE", "CAUTION", "BLOCKED"]
QualificationsStatus = Literal["MEETS", "GAPS", "UNKNOWN"]

# A location_match below this (0-100 scale, same as the rest of MatchOut)
# is treated as a real compatibility concern rather than noise.
_LOCATION_COMPATIBLE_THRESHOLD = 50.0


@dataclass(frozen=True)
class ApplicationViability:
    url_exists: bool
    direct_application: bool
    job_active: bool
    qualifications_status: QualificationsStatus
    location_compatible: bool | None
    visa_info_available: bool
    overall: OverallViability
    reasons: list[str] = field(default_factory=list)


def assess_application_viability(job: JobRow, match: JobMatch | None) -> ApplicationViability:
    reasons: list[str] = []

    url_exists = bool(job.application_url)
    # "Direct application" here means the stored URL is literally where the
    # candidate would apply — we have no separate landing-page URL to
    # distinguish a direct apply link from a general company careers page,
    # so this is honestly just url_exists restated for that specific
    # question rather than a fabricated distinction.
    direct_application = url_exists
    if not url_exists:
        reasons.append("No application URL on file")

    job_active = job.lifecycle_status == "ACTIVE"
    if not job_active:
        reasons.append(f"Job is no longer marked active ({job.lifecycle_status})")

    if match is None:
        qualifications_status: QualificationsStatus = "UNKNOWN"
        reasons.append("Not yet matched against your profile")
    elif match.hard_stop_reasons:
        qualifications_status = "GAPS"
        reasons.append("Hard-stop requirement(s) not met: " + "; ".join(match.hard_stop_reasons))
    elif match.missing_requirements:
        qualifications_status = "GAPS"
        reasons.append(
            "Missing: "
            + ", ".join(match.missing_requirements[:3])
            + ("…" if len(match.missing_requirements) > 3 else "")
        )
    else:
        qualifications_status = "MEETS"

    location_compatible: bool | None
    if match is None or match.location_match is None:
        location_compatible = None
    else:
        location_compatible = match.location_match >= _LOCATION_COMPATIBLE_THRESHOLD
        if not location_compatible:
            reasons.append("Location may not be compatible")

    visa_info_available = bool(job.visa_information)
    if not visa_info_available:
        reasons.append("No visa/sponsorship information provided")

    if not url_exists or not job_active:
        overall: OverallViability = "BLOCKED"
    elif qualifications_status == "GAPS" or location_compatible is False:
        overall = "CAUTION"
    else:
        overall = "VIABLE"

    return ApplicationViability(
        url_exists=url_exists,
        direct_application=direct_application,
        job_active=job_active,
        qualifications_status=qualifications_status,
        location_compatible=location_compatible,
        visa_info_available=visa_info_available,
        overall=overall,
        reasons=reasons,
    )
