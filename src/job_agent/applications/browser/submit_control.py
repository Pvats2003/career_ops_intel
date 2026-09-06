"""Real-execution checkpoint — deterministic, evidence-based identification
of the ONE control on a page that means "submit this application", never a
blind `page.click("button")` or `form.submit()`.

READ-ONLY: `find_submit_control()` only queries and reads attributes/text —
it never clicks, never types, never uploads. The only place in this
codebase that actually clicks a submit-shaped control is `job_agent.
applications.browser.session.BrowserSession.click_submit_control()`, called
by `applications browser-submit` (see `job_agent.cli.main`) only after this
function has returned exactly one, non-disabled, high-confidence candidate
AND every other safety check in that command has already passed.

CLASSIFICATION IS POSITIVE-EVIDENCE, NOT EXCLUSION: a control is a
candidate only if its visible text/value POSITIVELY matches one of a small
allowlist of application-submission phrases (`_POSITIVE_KEYWORDS`) --
never "anything that isn't obviously something else". A control whose text
ALSO matches a known non-submit action (`_NEGATIVE_KEYWORDS` -- Save,
Continue, Next, Upload, Login, Create account, Subscribe, Contact, Cancel,
and close relatives) is excluded even if it happens to also contain a
positive word, since real forms sometimes phrase a "Save and Continue"
step in a way that could otherwise be misread as final submission.

FAILS CLOSED, ALWAYS: zero candidates, more than one candidate, or a
disabled candidate are all reported as `control=None` with an explanatory
`reason` -- never a best-guess pick. The caller must show this to a human
and stop; nothing in this module ever raises past to a "just click
whatever's most likely" fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.applications.browser.session import BrowserSession

# Deliberately narrow: real application-submission controls overwhelmingly
# use one of these exact phrasings. Adding a new one should be a deliberate,
# reviewed decision, not a growing pile of guesses -- see the module
# docstring's "positive evidence" reasoning.
_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "submit application",
    "submit your application",
    "apply now",
    "apply for this job",
    "apply for this position",
    "submit",
    "apply",
)

# Anything matching one of these is excluded even if a positive keyword is
# also present -- e.g. "Save and Continue" contains no positive keyword
# here, but this list exists so a future addition to _POSITIVE_KEYWORDS
# (e.g. a bare "Next") can never silently turn a save/continue step into a
# false-positive submit control.
_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "save",
    "continue",
    "next",
    "back",
    "previous",
    "upload",
    "log in",
    "login",
    "log out",
    "logout",
    "sign in",
    "sign up",
    "create account",
    "register",
    "subscribe",
    "contact",
    "cancel",
    "close",
    "skip",
    "later",
    "reset",
    "clear",
    "edit",
    "delete",
    "remove",
    "preview",
    "download",
)

# Native form controls only -- an arbitrary [role="button"] on the page is
# not considered, deliberately: this codebase has no way to confirm a
# generic ARIA-role element behaves like a real submit control (e.g. that
# activating it actually submits a <form>), so extending detection to
# those would trade a structural guarantee for a guess. A real form's
# actual submit control is essentially always one of these three.
_CANDIDATE_SELECTOR = 'button, input[type="submit"], input[type="button"]'


@dataclass(frozen=True)
class SubmitControlCandidate:
    """A single, uniquely-selectable, high-confidence submit control."""

    selector: str
    label: str
    disabled: bool


@dataclass(frozen=True)
class SubmitControlResult:
    """`control` is populated ONLY when detection found exactly one
    non-disabled, high-confidence candidate. Any other outcome (none,
    several, or a disabled one) leaves `control=None` and explains why in
    `reason` -- the caller must stop and require a human, never guess."""

    control: SubmitControlCandidate | None
    reason: str


def _label_of(el: object) -> str:
    text = (el.text_content() or "").strip()  # type: ignore[attr-defined]
    if text:
        return text
    value = el.get_attribute("value") or ""  # type: ignore[attr-defined]
    return value.strip()


def _is_disabled(el: object) -> bool:
    return bool(el.get_attribute("disabled") is not None or el.is_disabled())  # type: ignore[attr-defined]


def _matches_any(normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in normalized for keyword in keywords)


def find_submit_control(session: BrowserSession) -> SubmitControlResult:
    """Read-only. Queries every `<button>`/`input[type=submit]`/
    `input[type=button]` currently visible in the DOM, classifies each by
    its own text/value only (never by position, never by CSS class,
    never by guessing intent from surrounding context), and returns
    exactly one candidate only when confidence is unambiguous."""
    elements = session.query_all(_CANDIDATE_SELECTOR)
    candidates: list[SubmitControlCandidate] = []
    for index, el in enumerate(elements):
        if not el.is_visible():  # type: ignore[attr-defined]
            continue
        label = _label_of(el)
        if not label:
            continue
        normalized = label.strip().lower()
        if _matches_any(normalized, _NEGATIVE_KEYWORDS):
            continue
        if not _matches_any(normalized, _POSITIVE_KEYWORDS):
            continue

        element_id = el.get_attribute("id")  # type: ignore[attr-defined]
        if element_id:
            selector = f"#{element_id}"
        else:
            selector = f":nth-match({_CANDIDATE_SELECTOR}, {index + 1})"
        candidates.append(
            SubmitControlCandidate(selector=selector, label=label, disabled=_is_disabled(el))
        )

    if not candidates:
        return SubmitControlResult(
            control=None,
            reason=(
                "no control on the page has text/value matching a known "
                "application-submission phrase (e.g. \"Submit Application\", \"Apply\") — "
                "refusing to guess."
            ),
        )
    if len(candidates) > 1:
        labels = ", ".join(repr(c.label) for c in candidates)
        return SubmitControlResult(
            control=None,
            reason=f"multiple plausible submit controls found ({labels}) — refusing to guess.",
        )

    control = candidates[0]
    if control.disabled:
        return SubmitControlResult(
            control=None,
            reason=f"the only candidate submit control ({control.label!r}) is disabled.",
        )
    return SubmitControlResult(control=control, reason="")
