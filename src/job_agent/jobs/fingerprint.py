"""Deterministic job deduplication fingerprint — BUILD PROMPT section 8.

Two fingerprints are computed, serving different purposes:

* `identity_key(source, source_job_id)` — exact identity within one source.
  Re-scanning the same source and seeing the same source_job_id again is
  the same job, full stop; used to decide "update" vs "insert" for a single
  source's postings.

* `compute_job_fingerprint(job)` — a content-based fingerprint (normalized
  company + title + location + canonicalized application URL) used to catch
  the SAME underlying job posted across multiple portals (e.g. a company's
  own career page and its Greenhouse board). This is a deterministic
  heuristic, not semantic similarity — true semantic dedup (comparing
  descriptions with embeddings) is Phase 3+ and layers on top of this, it
  does not replace it.

Neither fingerprint is a substitute for keeping the original per-source
row; BUILD PROMPT section 54 requires never losing historical data, so
dedup means "don't re-apply", not "delete the duplicate row".
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from job_agent.jobs.schema import Job


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def canonicalize_url(url: str) -> str:
    """Strip query string, fragment, and trailing slash — tracking
    parameters (utm_*, gh_src, etc.) must not defeat dedup."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def identity_key(source: str, source_job_id: str) -> str:
    return f"{source}:{source_job_id}"


def compute_job_fingerprint(job: Job) -> str:
    parts = [
        _normalize_text(job.company),
        _normalize_text(job.title),
        _normalize_text(job.location or ""),
        canonicalize_url(job.application_url),
    ]
    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
