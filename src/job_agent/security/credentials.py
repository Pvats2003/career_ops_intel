"""Credential-provider abstraction — Phase 6C groundwork.

============================================================================
PHASE 6C IS GROUNDWORK ONLY. THIS MODULE IS DORMANT.
============================================================================
REAL CREDENTIALS: NONE — nothing in this module ever holds, reads, or
    accepts a real ATS credential. `NullCredentialStore`, the only
    implementation shipped in `src/`, is structurally incapable of
    returning a value for any name — it holds no credential source at all.
REAL SUBMISSIONS: NONE — no code path anywhere reachable from this module
    can submit an application.
REAL NETWORK SUBMISSION CALLS: NONE — this module makes no network call of
    any kind (there is no `httpx`/`requests`/socket import here, checked by
    `tests/unit/test_credentials.py`'s structural tests).
BROWSER AUTOMATION: NONE.
============================================================================

WHAT THIS IS: a minimal, provider-agnostic interface (`CredentialProvider`)
that a *future* real `ApplicationProvider` would accept at construction
time to obtain whatever secret it needs to authenticate against a real ATS
platform — modeled on the exact same "abstraction before any real
implementation" pattern this project has used throughout (`ApplicationProvider`
existed for two phases before `StructuredATSProvider`; `SUBMISSION_UNCERTAIN`
existed in the state machine for a full phase before any provider could
reach it). Building the interface now, with its safety properties proven by
adversarial tests now, means a future live-execution phase adds a real
implementation against an already-reviewed contract instead of inventing
credential handling under pressure at the same time it's trying to ship a
real integration.

WHAT THIS IS NOT: this module is never imported by `job_agent.applications.
service`, `job_agent.applications.provider`, any concrete provider, or
`job_agent.cli.main` — it has no consumer anywhere in this codebase yet
(enforced by `tests/unit/test_credentials.py::test_nothing_in_src_imports_
this_module_outside_itself`). It grants no new capability to anything. A
future phase that wires a real `ApplicationProvider` to a real
`CredentialProvider` implementation is an explicit, reviewed, separate
change — never an incidental side effect of this module existing.

WHY THERE IS NO ENVIRONMENT-VARIABLE-BACKED IMPLEMENTATION HERE: it would be
easy to add an `EnvCredentialStore` that reads `os.environ`, and it would
still be "dormant" in the sense that nothing calls it — but that is a
weaker safety property than what this phase ships. `NullCredentialStore`
cannot return a real credential even if one is sitting in the process
environment right now, because it never reads the environment at all. A
future phase that adds a real credential source should do so as its own
reviewed, tested addition, not inherit one built speculatively here.

============================================================================
PREREQUISITES FOR ANY FUTURE LIVE-EXECUTION PHASE
============================================================================
None of the following exist yet. Every one of them is required — not just
"a real credential" — before any phase may enable a real submission:

1. `config/preferences.yaml` fully filled in by the candidate (salary,
   visa/work authorization, relocation) — as of Phase 6C these are still
   all `UNKNOWN`, and per `config/rules.yaml` any application question
   touching them must route to a human, never be guessed.
2. A real credential source implementation (e.g. an environment-variable-
   or vault-backed `CredentialProvider`) added and wired to a real
   provider as its own explicit, reviewed change — not inherited from
   this phase.
3. A real credential actually configured via `.env` (never committed,
   never logged), with this module's redaction guarantees re-verified
   against that real secret's actual shape, not just synthetic
   look-alikes.
4. A real provider's `submit()` implemented, reviewed, and adversarially
   tested to at least the same depth as `StructuredATSProvider`'s Phase
   6B review.
5. A real, tested verification path producing genuine `SubmissionEvidence`
   — see `job_agent.applications.verification_contract`'s module
   docstring for why shape-validity alone (what that module checks) is
   not sufficient; genuine provenance requires an independent, real
   signal this phase's validator cannot provide.
6. An explicit, small, human-curated allowlist of postings — never
   unbounded.
7. Automation level capped low with mandatory human approval per
   submission (never level 4 / unattended, at least initially).
8. Explicit, separate human sign-off on that live-execution phase's own
   scope — the same stop-and-wait review cadence every phase in this
   project (including this one) has gone through.
"""

from __future__ import annotations

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
            "real credential source (Phase 6C is dormant groundwork only) — "
            "a future, explicitly-reviewed phase must add and wire one "
            "before any real credential can be used."
        )
