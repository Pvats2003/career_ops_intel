"""Real-execution checkpoint — evidence-based post-submit-click
verification. "The click did not raise an exception" is never treated as
"the application was submitted" — see module docstring reasoning in
`job_agent.applications.providers.real_structured_ats` for the identical
principle applied to HTTP-based submission; this module is the browser
equivalent.

Collects only what is ACTUALLY observable in the live DOM after a submit
click: whether the page navigated, whether the just-filled form's own
fields are still present, and whether the visible page text contains a
generic, real-world-plausible confirmation phrase. Requires at least TWO
independent signals to agree before returning any evidence at all —
`page.click()` returning without an exception is exactly ONE signal on its
own (and one this module never even looks at, since `BrowserSession.
click_submit_control` already succeeded or raised before this runs), never
sufficient by itself.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from job_agent.applications.browser.inspector import field_selector
from job_agent.applications.browser.session import BrowserSession
from job_agent.applications.browser.snapshot import HumanReviewSnapshot
from job_agent.applications.schema import SubmissionEvidence

# Deliberately generic, real-world-plausible confirmation phrasing — never
# a fixture-specific marker (e.g. a data-* attribute this project's own
# synthetic HTML happens to use), so this logic is honestly the same logic
# that would run against a real target, even though only the local
# synthetic fixture actually exercises it in this checkpoint.
_CONFIRMATION_PHRASES: tuple[str, ...] = (
    "thank you for applying",
    "thank you for your application",
    "application received",
    "application submitted",
    "successfully submitted",
    "your application has been submitted",
    "we've received your application",
    "we have received your application",
    "application complete",
)


def _strip_query_and_fragment(url: str) -> str:
    """A GET-method HTML form (some real ATS forms, and this project's
    own local synthetic fixture) serializes every field VALUE into the
    resulting URL's query string -- including the candidate's own name/
    email/phone/etc. `confirmation_url` is stored in a database column
    and copied into an `ApplicationEvent`'s audit details, so it must
    never carry that. Keeps scheme/host/path only (still enough to show
    "this really did navigate to the platform's own confirmation page")
    and drops the query string and fragment unconditionally, regardless
    of whether this particular submission happened to use GET or POST."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def collect_post_submit_evidence(
    session: BrowserSession,
    *,
    pre_submit_url: str,
    filled_snapshot: HumanReviewSnapshot,
) -> SubmissionEvidence | None:
    """Read-only. Returns `None` (never a fabricated `SubmissionEvidence`)
    unless BOTH of the following hold:
      1. the visible page text contains a generic confirmation phrase
         (MANDATORY -- a navigation with no confirmation wording is never
         enough on its own: "page navigation occurred" is exactly the
         kind of weak signal this module must never treat as success,
         since navigating away could just as easily mean an error page,
         a redirect, or something unrelated)
      2. AT LEAST ONE corroborating signal also holds: the page actually
         navigated away from the pre-submit URL, OR the just-filled
         form's own fields are no longer present in the DOM
    """
    url_changed = session.current_url != pre_submit_url

    still_present = any(
        session.query_all(field_selector(f.field_id))
        for f in filled_snapshot.fields
        if f.field_type != "password"
    )
    form_gone = not still_present

    visible_text = session.visible_text().lower()
    confirmation_phrase = next(
        (phrase for phrase in _CONFIRMATION_PHRASES if phrase in visible_text), None
    )

    if confirmation_phrase is None:
        return None
    if not (url_changed or form_gone):
        return None

    return SubmissionEvidence(
        confirmation_url=_strip_query_and_fragment(session.current_url) if url_changed else None,
        confirmation_text=confirmation_phrase,
    )
