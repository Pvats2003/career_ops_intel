"""Phase 6D Stage 2 — `browser_application` as a first-class provider in
`build_application_provider()`'s existing config-driven resolution path.

Every test constructs its own local, temporary target-allowlist fixture
file (never the committed `config/fixtures/browser_application_targets.
example.yaml`, which stays untouched) and mutates only a deep copy of
`real_config.automation` (never the shared, session-scoped `real_config`
fixture itself). No test in this file opens a real or even a local
Playwright browser — `BrowserApplicationProvider.__init__` only stores
whatever `browser` object it's given, so a bare sentinel object stands in
for a real `playwright.sync_api.Browser` throughout.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from job_agent.applications.provider import ManualReviewProvider
from job_agent.applications.providers.browser_application import (
    BrowserApplicationProvider,
    load_browser_application_targets,
)
from job_agent.applications.providers.structured_ats import StructuredATSProvider
from job_agent.applications.service import build_application_provider
from job_agent.config.loader import AppConfig
from job_agent.db.models import Job as JobRow

_FAKE_BROWSER = object()


def _config_with(real_config, **browser_application_overrides) -> AppConfig:
    """A config identical to `real_config` except for a deep-copied
    `automation` section, so mutating it never leaks into other tests
    sharing the session-scoped `real_config` fixture."""
    automation = real_config.automation.model_copy(deep=True)
    for key, value in browser_application_overrides.items():
        setattr(automation.application_provider.browser_application, key, value)
    return AppConfig(
        env=real_config.env,
        profile=real_config.profile,
        preferences=real_config.preferences,
        sources=real_config.sources,
        automation=automation,
        rules=real_config.rules,
    )


def _write_targets(tmp_path: Path, *urls: str, name: str = "targets.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.dump({"target_urls": list(urls)}))
    return path


def _job(job_id: int, application_url: str | None) -> JobRow:
    job = JobRow(
        source_id=1, source_job_id=str(job_id), company_id=1,
        company_name="Acme", title="Engineer",
        application_url=application_url, job_fingerprint=f"fp-{job_id}",
    )
    job.id = job_id
    return job


# ==========================================================================
# 1. load_browser_application_targets() — the loader in isolation
# ==========================================================================
class TestLoadBrowserApplicationTargets:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="target file not found"):
            load_browser_application_targets(tmp_path / "does-not-exist.yaml")

    def test_duplicate_url_raises_value_error(self, tmp_path):
        path = _write_targets(tmp_path, "https://a.example.test/apply", "https://a.example.test/apply")
        with pytest.raises(ValueError, match="duplicate application_url"):
            load_browser_application_targets(path)

    def test_valid_file_returns_urls(self, tmp_path):
        path = _write_targets(
            tmp_path, "https://a.example.test/apply", "https://b.example.test/apply"
        )
        urls = load_browser_application_targets(path)
        assert urls == ("https://a.example.test/apply", "https://b.example.test/apply")

    def test_empty_file_returns_empty_tuple(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text(yaml.dump({"target_urls": []}))
        assert load_browser_application_targets(path) == ()


# ==========================================================================
# 2. Existing provider behavior is completely unchanged
# ==========================================================================
class TestExistingProviderBehaviorUnchanged:
    def test_default_config_still_returns_manual_review(self, real_config):
        provider = build_application_provider(real_config, [])
        assert isinstance(provider, ManualReviewProvider)

    def test_structured_ats_still_resolves_without_a_browser_argument(self, tmp_path, real_config):
        fixture = tmp_path / "structured_ats_fixture.yaml"
        fixture.write_text(
            yaml.dump(
                {
                    "forms": [
                        {
                            "application_url": "https://ats.example.test/job-1",
                            "ats_application_url": "https://ats.example.test/job-1/apply",
                            "ats_application_id": "id-1",
                            "captcha_present": False,
                            "mfa_present": False,
                            "consent_required": False,
                            "fields": [
                                {
                                    "field_id": "f1",
                                    "label": "Tell me about yourself.",
                                    "field_type": "TEXTAREA",
                                }
                            ],
                        }
                    ]
                }
            )
        )
        automation = real_config.automation.model_copy(deep=True)
        automation.application_provider.provider = "structured_ats"
        automation.application_provider.structured_ats.enabled = True
        automation.application_provider.structured_ats.fixture_path = str(fixture)
        config = AppConfig(
            env=real_config.env, profile=real_config.profile,
            preferences=real_config.preferences, sources=real_config.sources,
            automation=automation, rules=real_config.rules,
        )
        job = _job(1, "https://ats.example.test/job-1")
        provider = build_application_provider(config, [job])
        assert isinstance(provider, StructuredATSProvider)

    def test_browser_application_selected_but_not_enabled_falls_back_to_manual_review(
        self, real_config
    ):
        config = _config_with(real_config, enabled=False)
        config.automation.application_provider.provider = "browser_application"
        provider = build_application_provider(config, [])
        assert isinstance(provider, ManualReviewProvider)


# ==========================================================================
# 3. browser_application construction succeeds with a test configuration
# ==========================================================================
class TestBrowserApplicationConstruction:
    def test_constructs_provider_with_allowlisted_job_only(self, tmp_path, real_config):
        allowed_url = "https://careers.example.test/acme/apply"
        targets_path = _write_targets(tmp_path, allowed_url)
        config = _config_with(real_config, enabled=True, target_urls_path=str(targets_path))
        config.automation.application_provider.provider = "browser_application"

        allowed_job = _job(1, allowed_url)
        excluded_job = _job(2, "https://not-on-the-list.example.test/apply")

        provider = build_application_provider(
            config, [allowed_job, excluded_job], browser=_FAKE_BROWSER
        )

        assert isinstance(provider, BrowserApplicationProvider)
        assert provider._target_urls == {1: allowed_url}  # noqa: SLF001 — asserting internal state directly, the ABC exposes no getter
        assert provider._browser is _FAKE_BROWSER  # noqa: SLF001

    def test_job_with_no_application_url_is_skipped(self, tmp_path, real_config):
        targets_path = _write_targets(tmp_path, "https://careers.example.test/acme/apply")
        config = _config_with(real_config, enabled=True, target_urls_path=str(targets_path))
        config.automation.application_provider.provider = "browser_application"

        job_without_url = _job(1, None)
        provider = build_application_provider(config, [job_without_url], browser=_FAKE_BROWSER)

        assert isinstance(provider, BrowserApplicationProvider)
        assert provider._target_urls == {}  # noqa: SLF001

    def test_resume_path_is_the_shared_candidate_resume(self, tmp_path, real_config):
        targets_path = _write_targets(tmp_path, "https://careers.example.test/acme/apply")
        config = _config_with(real_config, enabled=True, target_urls_path=str(targets_path))
        config.automation.application_provider.provider = "browser_application"

        provider = build_application_provider(config, [], browser=_FAKE_BROWSER)

        assert provider._resume_path == config.env.candidate_dir / "resume_master.docx"  # noqa: SLF001


# ==========================================================================
# 4. Missing/invalid configuration fails safely, never silently
# ==========================================================================
class TestFailsSafely:
    def test_missing_browser_argument_raises_value_error(self, tmp_path, real_config):
        targets_path = _write_targets(tmp_path, "https://careers.example.test/acme/apply")
        config = _config_with(real_config, enabled=True, target_urls_path=str(targets_path))
        config.automation.application_provider.provider = "browser_application"

        with pytest.raises(ValueError, match="no live browser was supplied"):
            build_application_provider(config, [])

    def test_missing_fixture_file_raises_file_not_found_even_with_a_browser(
        self, tmp_path, real_config
    ):
        config = _config_with(
            real_config, enabled=True, target_urls_path=str(tmp_path / "missing.yaml")
        )
        config.automation.application_provider.provider = "browser_application"

        with pytest.raises(FileNotFoundError):
            build_application_provider(config, [], browser=_FAKE_BROWSER)

    def test_duplicate_target_url_raises_value_error_even_with_a_browser(
        self, tmp_path, real_config
    ):
        targets_path = _write_targets(
            tmp_path, "https://careers.example.test/acme/apply", "https://careers.example.test/acme/apply"
        )
        config = _config_with(real_config, enabled=True, target_urls_path=str(targets_path))
        config.automation.application_provider.provider = "browser_application"

        with pytest.raises(ValueError, match="duplicate application_url"):
            build_application_provider(config, [], browser=_FAKE_BROWSER)

    def test_never_falls_back_to_manual_review_on_missing_browser(self, tmp_path, real_config):
        """A missing browser must raise, not silently substitute another
        provider — silent substitution would be a far worse failure mode
        than a loud, actionable error."""
        targets_path = _write_targets(tmp_path, "https://careers.example.test/acme/apply")
        config = _config_with(real_config, enabled=True, target_urls_path=str(targets_path))
        config.automation.application_provider.provider = "browser_application"

        try:
            build_application_provider(config, [])
        except ValueError:
            pass
        else:
            pytest.fail("expected ValueError, got a provider instead of a raised exception")
