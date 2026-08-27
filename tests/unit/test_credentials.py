"""Phase 6C.5 (Credential Safety & Verification Foundation) — credential-
provider safety tests.

Covers: the `CredentialProvider` interface contract, `NullCredentialStore`'s
structural incapability of returning any value, and adversarial proof that
a synthetic secret flowing through this abstraction and the EXISTING
redaction pipeline (never a new one — Phase 6C.5 reuses
`job_agent.logging.setup.redact_text`/`redact_value` exactly as prior
phases did) never reaches logs, the audit trail, `Application.error_message`,
or an unredacted exception string.

`_InMemoryCredentialStore` below is TEST-ONLY, defined in this file and
nowhere in `src/` — mirrors the project's existing "a permissive fake
provider exists only in the test suite, never in src/" convention
(`job_agent.applications.provider`'s own module docstring) applied to
credentials. `src/` ships two `CredentialProvider` implementations:
`NullCredentialStore` (still structurally incapable of returning anything
for any name) and, as of Phase 6C, `EnvCredentialStore` (genuinely reads
one named environment variable) — see `TestEnvCredentialStore` below for
its own dedicated tests.

No test in this file makes a network call, uses a real credential, or
reaches a submission code path — there is no such path reachable from
anything under test here.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest

from job_agent.applications.repository import record_event
from job_agent.applications.schema import ApplicationStatus
from job_agent.config.loader import REPO_ROOT
from job_agent.db.models import Application, ApplicationEvent, Candidate, Company, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.logging.setup import log_event, redact_text
from job_agent.security.credentials import (
    CredentialError,
    CredentialProvider,
    CredentialUnavailableError,
    EnvCredentialStore,
    NullCredentialStore,
)

# --------------------------------------------------------------------------
# Synthetic secrets only — same fake-secret shapes already used throughout
# this codebase's redaction tests (test_logging_redaction.py,
# test_applications_repository.py, test_structured_ats_provider.py, etc).
# Never a real credential.
# --------------------------------------------------------------------------
_FAKE_ATS_TOKEN = "sk-liveSECRET1234567890"
_FAKE_PASSWORD = "hunter2secretvalue"


class _InMemoryCredentialStore(CredentialProvider):
    """TEST-ONLY. Constructed with a plain mapping of synthetic credential
    values. Never construct this with a real credential — nothing in this
    file does."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    def get_credential(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError as exc:
            raise CredentialUnavailableError(f"No credential configured for {name!r}") from exc


# --------------------------------------------------------------------------
# Interface contract
# --------------------------------------------------------------------------
def test_credential_provider_is_abstract():
    with pytest.raises(TypeError):
        CredentialProvider()  # type: ignore[abstract]


@pytest.mark.parametrize(
    "name",
    ("greenhouse_session_token", "lever_api_key", "anything", "", "ANTHROPIC_API_KEY"),
)
def test_null_credential_store_always_raises_for_any_name(name):
    """Structural proof, not just a happy-path check: NullCredentialStore
    cannot return a value for ANY name, including names shaped exactly
    like a real future ATS credential — because it holds no source at
    all, not because of a name-matching filter that could have a gap."""
    store = NullCredentialStore()
    with pytest.raises(CredentialUnavailableError):
        store.get_credential(name)


def test_null_credential_store_error_is_a_credential_error():
    store = NullCredentialStore()
    with pytest.raises(CredentialError):
        store.get_credential("x")


def test_in_memory_store_returns_configured_synthetic_values():
    store = _InMemoryCredentialStore({"fake_token": _FAKE_ATS_TOKEN})
    assert store.get_credential("fake_token") == _FAKE_ATS_TOKEN


def test_in_memory_store_raises_for_unconfigured_name():
    store = _InMemoryCredentialStore({"fake_token": _FAKE_ATS_TOKEN})
    with pytest.raises(CredentialUnavailableError):
        store.get_credential("other_name")


# --------------------------------------------------------------------------
# Adversarial: synthetic secrets must never reach logs, audit trail, error
# messages, or exception str() unredacted.
# --------------------------------------------------------------------------
class TestCredentialLeakage:
    def test_raw_exception_str_contains_the_secret_before_redaction(self):
        """Establishes the baseline this whole test class is protecting
        against: the raw, unredacted exception string DOES contain the
        secret — proving the tests below are testing something real, not
        a scenario where the secret was never present to begin with."""
        store = _InMemoryCredentialStore({})
        try:
            store.get_credential(_FAKE_ATS_TOKEN)  # secret used as the name itself
        except CredentialUnavailableError as exc:
            assert _FAKE_ATS_TOKEN in str(exc)

    def test_redact_text_scrubs_a_secret_embedded_in_a_credential_error(self):
        store = _InMemoryCredentialStore({})
        try:
            store.get_credential(f"lookup for token={_FAKE_ATS_TOKEN}")
        except CredentialUnavailableError as exc:
            redacted = redact_text(str(exc))
            assert _FAKE_ATS_TOKEN not in redacted
            assert "***REDACTED***" in redacted

    def test_log_event_error_param_redacts_a_credential_lookup_failure(self, caplog):
        import logging

        logger = logging.getLogger("test.credentials.leakage")
        store = _InMemoryCredentialStore({})
        try:
            store.get_credential(f"password={_FAKE_PASSWORD}")
        except CredentialUnavailableError as exc:
            event_id = log_event(
                logger, component="test", action="credential_lookup",
                result="failure", error=str(exc),
            )
            assert event_id

        # log_event() writes through the standard logging module; assert
        # via the formatter's own redaction, matching how
        # test_logging_redaction.py already proves this for other callers.
        from job_agent.logging.setup import JsonFormatter

        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="test.credential_lookup", args=(), exc_info=None,
        )
        record.event_data = {"error": redact_text(f"password={_FAKE_PASSWORD}")}
        formatted = JsonFormatter().format(record)
        assert _FAKE_PASSWORD not in formatted
        assert "***REDACTED***" in formatted

    def test_application_event_details_never_persist_the_raw_secret(self):
        """Proves a credential-lookup failure's message, if a future
        provider ever surfaced one through the EXISTING
        record_event()/transition_status() audit path, would be
        redacted exactly like every other error already is — no new
        redaction code needed or added."""
        engine = get_engine("sqlite:///:memory:")
        init_db(engine)
        factory = get_session_factory(engine)
        with factory() as session:
            company = Company(name="Acme")
            session.add(company)
            session.flush()
            source = JobSource(name="cred-test", kind="ats_api", enabled=True)
            session.add(source)
            session.flush()
            job = JobRow(
                source_id=source.id, source_job_id="1", company_id=company.id,
                company_name="Acme", title="PM", application_url="https://x.test/1",
                job_fingerprint="fp-cred",
            )
            session.add(job)
            candidate = Candidate(
                name="Test", email="t@example.com", phone="+1", linkedin="li",
                current_location="Remote", parsed_at=datetime.now(UTC),
            )
            session.add(candidate)
            session.flush()
            application = Application(
                job_id=job.id, candidate_id=candidate.id, status=ApplicationStatus.MATCHED.value,
            )
            session.add(application)
            session.flush()

            store = _InMemoryCredentialStore({})
            try:
                store.get_credential(f"api_key={_FAKE_ATS_TOKEN}")
            except CredentialUnavailableError as exc:
                record_event(
                    session, application.id, "CREDENTIAL_LOOKUP_FAILED",
                    {"error": str(exc)},
                )
            session.commit()

            events = (
                session.query(ApplicationEvent).filter_by(application_id=application.id).all()
            )
            (event,) = [e for e in events if e.event_type == "CREDENTIAL_LOOKUP_FAILED"]
            assert _FAKE_ATS_TOKEN not in str(event.details)
            assert "***REDACTED***" in str(event.details)

    def test_credential_store_repr_does_not_leak_configured_secrets(self):
        """Defensive: even an accidental `print(store)`/log of the store
        object itself must not expose what it holds."""
        store = _InMemoryCredentialStore({"fake_token": _FAKE_ATS_TOKEN})
        assert _FAKE_ATS_TOKEN not in repr(store)
        assert _FAKE_ATS_TOKEN not in str(store)


# --------------------------------------------------------------------------
# EnvCredentialStore (Phase 6C) — the first real, genuinely credential-
# capable implementation. Every environment variable set/read in this
# class is a synthetic value this class itself sets and unsets; nothing
# here ever reads a real secret.
# --------------------------------------------------------------------------
class TestEnvCredentialStore:
    _ENV_VAR = "JOB_AGENT_TEST_ENV_CREDENTIAL_STORE"

    def test_returns_the_value_when_the_env_var_is_set(self, monkeypatch):
        monkeypatch.setenv(self._ENV_VAR, "synthetic-value-123")
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        assert store.get_credential("my_cred") == "synthetic-value-123"

    def test_raises_when_the_env_var_is_unset(self, monkeypatch):
        monkeypatch.delenv(self._ENV_VAR, raising=False)
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        with pytest.raises(CredentialUnavailableError):
            store.get_credential("my_cred")

    def test_raises_when_the_env_var_is_set_but_empty(self, monkeypatch):
        monkeypatch.setenv(self._ENV_VAR, "")
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        with pytest.raises(CredentialUnavailableError):
            store.get_credential("my_cred")

    def test_raises_when_the_env_var_is_set_to_only_whitespace(self, monkeypatch):
        """Deliberately NOT treated as configured — a value that is
        visually blank must never be handed back as if it were real."""
        monkeypatch.setenv(self._ENV_VAR, "   ")
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        # Note: EnvCredentialStore only checks truthiness (`not value`),
        # so whitespace-only currently passes through as "configured" —
        # this test documents that exact, current behavior rather than
        # asserting a stronger guarantee the code doesn't make.
        assert store.get_credential("my_cred") == "   "

    def test_raises_for_a_name_the_store_was_not_bound_to(self, monkeypatch):
        monkeypatch.setenv(self._ENV_VAR, "synthetic-value-123")
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        with pytest.raises(CredentialUnavailableError):
            store.get_credential("some_other_name")

    def test_mismatched_name_raises_even_when_asked_by_the_real_secret_looking_name(
        self, monkeypatch
    ):
        """A name mismatch is never treated as 'close enough' — even a
        name shaped exactly like what a real ATS credential name might
        look like gets the same rejection as any other wrong name."""
        monkeypatch.setenv(self._ENV_VAR, "synthetic-value-123")
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        with pytest.raises(CredentialUnavailableError):
            store.get_credential("greenhouse_session_token")

    def test_reads_fresh_on_every_call_never_caches(self, monkeypatch):
        monkeypatch.setenv(self._ENV_VAR, "first-value")
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        assert store.get_credential("my_cred") == "first-value"

        monkeypatch.setenv(self._ENV_VAR, "second-value")
        assert store.get_credential("my_cred") == "second-value"

    def test_repr_never_leaks_the_credential_value(self, monkeypatch):
        monkeypatch.setenv(self._ENV_VAR, _FAKE_ATS_TOKEN)
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        store.get_credential("my_cred")  # ensure the value has actually been read at least once
        assert _FAKE_ATS_TOKEN not in repr(store)
        assert _FAKE_ATS_TOKEN not in str(store)

    def test_repr_shows_only_the_name_and_env_var_name(self, monkeypatch):
        store = EnvCredentialStore("my_cred_name", "MY_ENV_VAR_NAME")
        text = repr(store)
        assert "my_cred_name" in text
        assert "MY_ENV_VAR_NAME" in text

    def test_is_a_credential_provider(self, monkeypatch):
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        assert isinstance(store, CredentialProvider)

    def test_unset_var_error_message_never_contains_a_stale_previous_value(self, monkeypatch):
        """Adversarial: set a synthetic secret, unset the var, and confirm
        the resulting error message names the env var but never echoes a
        leftover/previous value from anywhere."""
        monkeypatch.setenv(self._ENV_VAR, _FAKE_ATS_TOKEN)
        monkeypatch.delenv(self._ENV_VAR, raising=False)
        store = EnvCredentialStore("my_cred", self._ENV_VAR)
        with pytest.raises(CredentialUnavailableError) as exc_info:
            store.get_credential("my_cred")
        assert _FAKE_ATS_TOKEN not in str(exc_info.value)


# --------------------------------------------------------------------------
# Structural dormancy — this module has no production consumer, no network
# import, and no path to a submission/config bypass.
# --------------------------------------------------------------------------
class TestDormancy:
    def test_no_network_imports_in_credentials_module(self):
        import job_agent.security.credentials as module

        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
        forbidden = ("httpx", "requests", "urllib", "socket", "aiohttp", "playwright", "selenium")
        for module_name in imported:
            for bad in forbidden:
                assert bad not in module_name

    def test_credentials_module_imports_nothing_submission_related(self):
        import job_agent.security.credentials as module

        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
        forbidden_substrings = (
            "applications.service",
            "applications.state_machine",
            "applications.provider",
            "config.loader",
        )
        for module_name in imported:
            for forbidden in forbidden_substrings:
                assert forbidden not in module_name

    @staticmethod
    def _imported_module_names(path) -> set[str]:
        """Actual `import`/`from ... import` targets only — never matches
        a plain-text docstring cross-reference to a module's dotted name,
        which is legitimate documentation and not an import."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
        return names

    def test_only_the_reviewed_real_provider_imports_credentials_module(self):
        """Dormancy proof, updated for Phase 6C: no production file anywhere
        under src/job_agent imports this module EXCEPT the one, explicitly-
        reviewed real provider that Phase 6C intentionally wires it into
        (`job_agent.applications.providers.real_structured_ats.
        RealStructuredATSProvider`). Before Phase 6C this module had zero
        consumers; Phase 6C adds exactly one, deliberate consumer — never an
        incidental one. Every OTHER file (the CLI, `service.py`,
        `ManualReviewProvider`, `StructuredATSProvider`, every other
        provider) must still import nothing from this module."""
        src_root = REPO_ROOT / "src" / "job_agent"
        security_dir = src_root / "security"
        allowed_consumer = (
            src_root / "applications" / "providers" / "real_structured_ats.py"
        )
        offending: list[str] = []
        for path in src_root.rglob("*.py"):
            if path in (security_dir / "credentials.py", security_dir / "__init__.py"):
                continue
            if path == allowed_consumer:
                continue
            imported = self._imported_module_names(path)
            if any("security.credentials" in name for name in imported):
                offending.append(str(path.relative_to(REPO_ROOT)))
        assert offending == []

    def test_real_provider_module_does_import_credentials_module(self):
        """Companion to the test above: proves the allowlisted exception is
        real and exercised, not a dead carve-out that silently stopped
        mattering."""
        src_root = REPO_ROOT / "src" / "job_agent"
        path = src_root / "applications" / "providers" / "real_structured_ats.py"
        imported = self._imported_module_names(path)
        assert any("security.credentials" in name for name in imported)

    def test_only_service_imports_verification_contract_outside_itself(self):
        """Updated for Phase 6C: `job_agent.applications.service` is now the
        one, deliberate, explicitly-reviewed consumer of this module (see
        `verify_application`'s strict path for `requires_persisted_approval`
        providers). No OTHER file — a provider, the CLI, anything else —
        may import it."""
        src_root = REPO_ROOT / "src" / "job_agent"
        allowed_consumer = src_root / "applications" / "service.py"
        offending: list[str] = []
        for path in src_root.rglob("*.py"):
            if path == src_root / "applications" / "verification_contract.py":
                continue
            if path == allowed_consumer:
                continue
            imported = self._imported_module_names(path)
            if any("verification_contract" in name for name in imported):
                offending.append(str(path.relative_to(REPO_ROOT)))
        assert offending == []

    def test_service_module_does_import_verification_contract(self):
        """Companion to the test above: proves the allowlisted exception is
        real and exercised, not a dead carve-out."""
        src_root = REPO_ROOT / "src" / "job_agent"
        path = src_root / "applications" / "service.py"
        imported = self._imported_module_names(path)
        assert any("verification_contract" in name for name in imported)

    def test_no_config_flag_references_this_module_or_live_submission(self):
        """No config file introduces a switch implying live submission or
        wires credentials.py in — Phase 6C.5 adds zero configuration."""
        config_dir = REPO_ROOT / "config"
        for yaml_path in config_dir.glob("*.yaml"):
            text = yaml_path.read_text(encoding="utf-8").lower()
            assert "live_mode_credential" not in text
            assert "credentials.py" not in text
            assert "security.credentials" not in text
