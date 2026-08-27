"""Credential-provider abstraction — Phase 6C.5 (Credential Safety &
Verification Foundation) groundwork, now extended by Phase 6C's first real
implementation.

============================================================================
PHASE 6C.5 — CREDENTIAL SAFETY & VERIFICATION FOUNDATION. GROUNDWORK.
PHASE 6C — CONTROLLED REAL-WORLD EXECUTION. `EnvCredentialStore` below is
this phase's first real, genuinely credential-capable implementation —
STILL STAGE 1 ONLY (see its own docstring): no real credential is
configured or read by anything in this repository or its test suite during
this implementation pass.

This module belongs to Phase 6C.5 (the `CredentialProvider` interface and
`NullCredentialStore`, both still fully dormant) plus Phase 6C
(`EnvCredentialStore`, the first implementation actually able to read a
real secret if one were ever set in the process environment).
============================================================================
REAL CREDENTIALS: NONE ARE READ BY THIS IMPLEMENTATION/TEST PASS — but this
    is no longer a structural guarantee of the module as a whole.
    `NullCredentialStore` remains structurally incapable of returning a
    value for any name — it holds no credential source at all.
    `EnvCredentialStore`, added in Phase 6C, genuinely reads a named
    environment variable and WOULD return a real secret if the process
    environment had one set for its bound `env_var_name`. Nothing in this
    repository or its test suite ever sets such a variable to a real
    value (see `tests/unit/test_credentials.py`'s CI-absence assertion) —
    the "no real credential" property in this pass holds because nothing
    configures one, not because the code is incapable of reading one.
REAL SUBMISSIONS: NONE — no code in this module can submit an application;
    `EnvCredentialStore` only ever returns a string value, nothing more.
REAL NETWORK SUBMISSION CALLS: NONE — this module makes no network call of
    any kind (there is no `httpx`/`requests`/socket import here, checked by
    `tests/unit/test_credentials.py`'s structural tests). Reading
    `os.environ` is not network I/O.
BROWSER AUTOMATION: NONE.
============================================================================

WHAT THIS IS: a minimal, provider-agnostic interface (`CredentialProvider`)
that a real `ApplicationProvider` accepts at construction time to obtain
whatever secret it needs to authenticate against a real ATS platform —
modeled on the exact same "abstraction before any real implementation"
pattern this project has used throughout (`ApplicationProvider` existed for
two phases before `StructuredATSProvider`; `SUBMISSION_UNCERTAIN` existed
in the state machine for a full phase before any provider could reach it).
`CredentialProvider` and `NullCredentialStore` were built with their safety
properties proven by adversarial tests first; `EnvCredentialStore` is the
real implementation that phase anticipated, added as its own explicit,
reviewed change against that already-reviewed contract.

WHAT `NullCredentialStore`/`CredentialProvider` STILL ARE NOT: this
abstraction is still never imported by `job_agent.applications.service`,
`job_agent.applications.provider`, `job_agent.cli.main`, or any *existing*
(pre-Phase-6C) concrete provider — those code paths are unchanged
(enforced by `tests/unit/test_credentials.py::test_nothing_in_src_imports_
this_module_outside_itself`, scoped to exclude only Phase 6C's own new,
explicitly-reviewed real-provider code). This module still grants no new
capability to any pre-existing code by merely existing.

`EnvCredentialStore`: see its own docstring below for the exact, narrow
scope of what it does and does not do.

============================================================================
PREREQUISITES FOR ANY FUTURE LIVE-EXECUTION (STAGE 2) PHASE
============================================================================
`EnvCredentialStore`'s existence satisfies prerequisite 2 below. The rest
are still not satisfied — every one of them (not just "a real credential")
is required before any phase may enable a REAL submission:

1. `config/preferences.yaml` fully filled in by the candidate (salary,
   visa/work authorization, relocation) — as of this pass these are
   still all `UNKNOWN`, and per `config/rules.yaml` any application question
   touching them must route to a human, never be guessed.
2. A real credential source implementation wired to a real provider as its
   own explicit, reviewed change. SATISFIED: `EnvCredentialStore` is that
   implementation. Still required before Stage 2: a real credential
   actually configured via `.env` (never committed, never logged) — none
   is configured by this pass.
3. This module's redaction guarantees re-verified against a real secret's
   actual shape, not just synthetic look-alikes — not yet done.
4. A real provider's `submit()` implemented, reviewed, and adversarially
   tested to at least the same depth as `StructuredATSProvider`'s Phase
   6B review, exercised only against synthetic credentials and
   mocked/local HTTP in this pass.
5. A real, tested verification path producing genuine `SubmissionEvidence`
   — see `job_agent.applications.verification_contract`'s module
   docstring for why shape-validity alone (what that module checks) is
   not sufficient; genuine provenance requires an independent, real
   signal this phase's validator cannot provide.
6. An explicit, small, human-curated allowlist of postings — never
   unbounded. This pass adds the allowlist mechanism; no real posting is
   added to it.
7. Automation level capped low with mandatory human approval per
   submission (never level 4 / unattended) — this pass makes persisted
   human approval unconditional for any provider that requires it,
   regardless of automation level.
8. Explicit, separate human sign-off selecting one real posting and
   authorizing the first controlled real-world test (Stage 2) — the same
   stop-and-wait review cadence every phase in this project (including
   this one) has gone through. This pass (Stage 1) does not have that
   sign-off and must not act as though it does.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class CredentialError(Exception):
    """Base class for any `CredentialProvider` failure."""


class CredentialUnavailableError(CredentialError):
    """Raised when a requested credential is not configured/available.

    This is the *only* outcome `NullCredentialStore` ever produces — there
    is no "credential found" path through it for any name, real or
    synthetic.
    """


class CredentialProvider(ABC):
    """Provider-agnostic interface for obtaining a named credential.

    Mirrors `job_agent.llm.provider.LLMProvider`'s shape deliberately:
    one abstract method, "not configured" is a raised error (never a
    silently-returned `None` a caller might forget to check), and the safe
    "nothing is configured" case gets its own named implementation
    (`NullCredentialStore`) rather than being encoded as a magic sentinel
    value.
    """

    @abstractmethod
    def get_credential(self, name: str) -> str:
        """Return the value of the named credential.

        Raises `CredentialUnavailableError` if `name` is not configured —
        never returns a guessed, default, or placeholder value.
        """


class NullCredentialStore(CredentialProvider):
    """The only production `CredentialProvider` implementation shipped in
    this phase. Holds no credential source of any kind — no environment
    variables, no file, no vault client, nothing — so it is structurally
    incapable of returning a value for any name. Every call raises
    `CredentialUnavailableError`.

    This is the safe default a future provider would receive until a real
    credential source is explicitly built and wired in as its own reviewed
    change.
    """

    def get_credential(self, name: str) -> str:
        raise CredentialUnavailableError(
            f"No credential is configured for {name!r}. This build ships no "
            "real credential source (Phase 6C.5 is dormant groundwork only) — "
            "a future, explicitly-reviewed phase must add and wire one "
            "before any real credential can be used."
        )


# ============================================================================
# PHASE 6C — the first real `CredentialProvider` implementation.
# ============================================================================
# REAL CREDENTIALS: only if the process environment genuinely has one set —
#     never during this implementation/test pass (see
#     `tests/unit/test_credentials.py`'s CI-absence assertion). Environment-
#     variable-only: never YAML, never a CLI argument, never hardcoded.
# REAL SUBMISSIONS: this class only ever returns a string value — it has no
#     ability to submit, verify, or make any network call itself.
# REAL NETWORK SUBMISSION CALLS: NONE — reading `os.environ` is not network
#     I/O.
# ============================================================================
class EnvCredentialStore(CredentialProvider):
    """Reads exactly one named credential from exactly one named
    environment variable — nothing else, nowhere else.

    Bound at construction to a single `(credential_name, env_var_name)`
    pair, deliberately not a general multi-credential registry: Phase 6C's
    "smallest possible first step" needs exactly one real credential for
    one real provider, and a caller must ask for it by the SAME
    `credential_name` the store was constructed with — `get_credential`
    with any other name raises `CredentialUnavailableError`, the same as
    it would for a genuinely unconfigured credential, never returning the
    wrong secret for a mismatched name.

    The credential value itself is read fresh from `os.environ` on every
    call (never cached on `self`) so nothing about this object's state
    ever needs to be treated as sensitive — `repr()`/`str()` of an
    `EnvCredentialStore` instance exposes only the credential's NAME and
    which env var it reads, never its value (see
    `tests/unit/test_credentials.py::TestEnvCredentialStoreLeakage`).

    An unset or empty environment variable raises `CredentialUnavailableError`
    — this class never falls back to a default, placeholder, or guessed
    value, and it never treats an empty string as "no credential" silently
    passed through as if it were a real one.
    """

    def __init__(self, credential_name: str, env_var_name: str) -> None:
        self._credential_name = credential_name
        self._env_var_name = env_var_name

    def __repr__(self) -> str:
        return (
            f"EnvCredentialStore(credential_name={self._credential_name!r}, "
            f"env_var_name={self._env_var_name!r})"
        )

    def get_credential(self, name: str) -> str:
        if name != self._credential_name:
            raise CredentialUnavailableError(
                f"This EnvCredentialStore is bound to {self._credential_name!r}, "
                f"not {name!r}."
            )
        value = os.environ.get(self._env_var_name)
        if not value:
            raise CredentialUnavailableError(
                f"Environment variable {self._env_var_name!r} is not set (or is "
                f"empty) — cannot provide credential {self._credential_name!r}."
            )
        return value
