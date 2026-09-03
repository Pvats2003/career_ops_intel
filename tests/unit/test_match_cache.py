"""AI-analysis cache key (job_agent.matching.cache) — Career OS Phase 16
cost control."""

from __future__ import annotations

from job_agent.db.models import Job as JobRow
from job_agent.matching.cache import compute_match_cache_key


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme", title="Business Analyst", description="SQL and Excel required.",
        requirements=None, preferred_qualifications=None, location="Remote",
        remote_type="remote", employment_type="full_time", job_fingerprint="fp",
    )
    base.update(overrides)
    return JobRow(**base)


def test_same_inputs_produce_same_key(real_profile, real_config):
    job = _job()
    key_a = compute_match_cache_key(real_profile, real_config, job)
    key_b = compute_match_cache_key(real_profile, real_config, job)
    assert key_a == key_b


def test_different_job_description_changes_key(real_profile, real_config):
    job_a = _job(description="SQL and Excel required.")
    job_b = _job(description="Python and Tableau required.")
    assert compute_match_cache_key(real_profile, real_config, job_a) != compute_match_cache_key(
        real_profile, real_config, job_b
    )


def test_different_job_title_changes_key(real_profile, real_config):
    job_a = _job(title="Business Analyst")
    job_b = _job(title="Product Manager")
    assert compute_match_cache_key(real_profile, real_config, job_a) != compute_match_cache_key(
        real_profile, real_config, job_b
    )


def test_key_is_a_stable_length_hex_digest(real_profile, real_config):
    key = compute_match_cache_key(real_profile, real_config, _job())
    assert len(key) == 64
    int(key, 16)  # never raises — must be valid hex
