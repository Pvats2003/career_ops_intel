"""AI-analysis caching — Career OS Phase 16 cost control.

"Do not send every job description to the expensive LLM" (BUILD PROMPT
Phase 16): a job that has already been matched, whose posting text
hasn't changed, against a candidate profile that hasn't changed, under
matching logic/config that hasn't changed, gets NO new LLM call on the
next search run — the previous `JobMatch` row is reused verbatim. Only
when any of those three things actually changed does this system pay for
a fresh semantic pass.

`MATCH_LOGIC_VERSION` is a manual escape hatch: bump it whenever
`job_agent.matching.deterministic`/`semantic`/`scoring`/`decision` change
in a way that would produce a different result for the same inputs —
every cache entry is invalidated on the next run.
"""

from __future__ import annotations

import hashlib
import json

from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig
from job_agent.db.models import Job as JobRow
from job_agent.resume.versioning import compute_profile_hash

MATCH_LOGIC_VERSION = "match_cache.v1"


def compute_match_cache_key(profile: CandidateProfile, config: AppConfig, job_row: JobRow) -> str:
    job_content = {
        "title": job_row.title,
        "company_name": job_row.company_name,
        "description": job_row.description,
        "requirements": job_row.requirements,
        "preferred_qualifications": job_row.preferred_qualifications,
        "location": job_row.location,
        "remote_type": job_row.remote_type,
        "employment_type": job_row.employment_type,
    }
    scoring_config = {
        "scoring_weights": config.automation.scoring_weights.model_dump(mode="json"),
        "matching": config.automation.matching.model_dump(mode="json"),
    }
    payload = {
        "logic_version": MATCH_LOGIC_VERSION,
        "profile_hash": compute_profile_hash(profile),
        "job_content": job_content,
        "scoring_config": scoring_config,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
