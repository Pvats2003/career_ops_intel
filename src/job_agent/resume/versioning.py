"""Content hashing for candidate profile versioning.

A version is defined by the exact bytes of its source files plus the exact
content of the profile parsed from them — not by "when it ran". Hashing
(rather than timestamps) is what lets `job_agent.resume.service` tell "the
source hasn't actually changed" apart from "someone re-ran `profile
parse`", so re-running it repeatedly doesn't spam a new row every time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import REPO_ROOT, AppConfig

# The exact set of files whose bytes determine a profile version's identity.
# resume_master.docx is listed first and is mandatory (it's the
# authoritative source per Phase 4's requirement); the rest are the
# human-authored intermediate files plus the config that feeds
# target_roles/preferences into the profile.
_SOURCE_FILE_NAMES = (
    "resume_master.docx",
    "profile.md",
    "experience.md",
    "projects.md",
    "skills.md",
    "education.md",
    "achievements.md",
)
_CONFIG_FILE_NAMES = ("profile.yaml", "preferences.yaml")


def compute_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_source_hashes(config: AppConfig) -> dict[str, str]:
    """Hash every file that determines a profile version's identity.

    Keyed by repo-relative path for readable, portable audit records.
    """
    candidate_dir = config.env.candidate_dir
    config_dir = config.env.config_dir

    paths = [candidate_dir / name for name in _SOURCE_FILE_NAMES]
    paths += [config_dir / name for name in _CONFIG_FILE_NAMES]

    hashes: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue  # missing candidate/*.md fails earlier, in the parser itself
        try:
            key = str(path.relative_to(REPO_ROOT))
        except ValueError:
            key = str(path)
        hashes[key] = compute_file_hash(path)
    return hashes


def compute_profile_hash(profile: CandidateProfile) -> str:
    """Hash the profile's semantic content, excluding `parsed_at` (which
    changes on every run regardless of whether anything meaningful did)."""
    data = profile.model_dump(mode="json", exclude={"parsed_at"})
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
