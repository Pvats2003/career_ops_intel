"""Phase 6D Stage 1 — narrow, single-origin browser session wrapper.

Mirrors `job_agent.applications.submission_http.SubmissionHttpClient`'s
central safety principle exactly, translated from HTTP to a browser:
bound at construction to exactly ONE target URL. There is no method
anywhere on this class that accepts a URL to navigate to — `load()` only
ever goes to the URL the session was constructed with. Every other method
that touches the page first re-checks the page is still on that bound
origin and raises `DomainDriftDetectedError` rather than continuing if a
redirect, a link, or a form's own action target moved it elsewhere.

STAGE 1: this class is only ever constructed, anywhere in this
repository, against a local synthetic HTTP server the test suite itself
serves on `127.0.0.1` — see `tests/unit/test_browser_provider.py`. No
production code path in this phase constructs it against any other
destination.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.sync_api import Browser, ElementHandle, Page


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class DomainDriftDetectedError(Exception):
    """Raised the instant this session observes itself on a different
    origin than the one it was bound to at construction — never silently
    followed. See module docstring."""

    def __init__(self, bound_origin: str, observed_origin: str) -> None:
        self.bound_origin = bound_origin
        self.observed_origin = observed_origin
        super().__init__(
            f"navigation left the bound origin {bound_origin!r}; now observed at "
            f"{observed_origin!r}. Hard-stopping rather than continuing."
        )


class BrowserSession:
    """POST-only-client-shaped browser wrapper: one bound target URL, a
    small set of named interaction methods (never a generic
    ``navigate(url)``), and an origin check before every DOM-touching
    call."""

    def __init__(
        self,
        target_url: str,
        *,
        browser: Browser,
        timeout_ms: float = 15_000,
    ) -> None:
        self._target_url = target_url
        self._bound_origin = _origin_of(target_url)
        self._browser = browser
        self._context = browser.new_context()
        self._page: Page = self._context.new_page()
        self._page.set_default_timeout(timeout_ms)
        self._loaded = False

    @property
    def target_url(self) -> str:
        return self._target_url

    @property
    def current_url(self) -> str:
        return self._page.url

    @property
    def page(self) -> Page:
        """Read-only escape hatch for the inspector, which only ever
        reads DOM structure — never navigates or submits anything."""
        self._assert_on_bound_origin()
        return self._page

    def load(self) -> None:
        """Navigate to the bound target URL. The only navigation this
        session ever performs to a caller-chosen destination."""
        self._page.goto(self._target_url)
        self._loaded = True
        self._assert_on_bound_origin()

    def _assert_on_bound_origin(self) -> None:
        if not self._loaded:
            return
        observed = _origin_of(self._page.url)
        if observed != self._bound_origin:
            raise DomainDriftDetectedError(self._bound_origin, observed)

    def query_all(self, selector: str) -> list[ElementHandle]:
        self._assert_on_bound_origin()
        return self._page.query_selector_all(selector)

    def fill_text(self, selector: str, value: str) -> None:
        self._assert_on_bound_origin()
        self._page.fill(selector, value)
        self._assert_on_bound_origin()

    def select_option(self, selector: str, value: str) -> None:
        self._assert_on_bound_origin()
        self._page.select_option(selector, value)
        self._assert_on_bound_origin()

    def check(self, selector: str) -> None:
        self._assert_on_bound_origin()
        self._page.check(selector)
        self._assert_on_bound_origin()

    def uncheck(self, selector: str) -> None:
        self._assert_on_bound_origin()
        self._page.uncheck(selector)
        self._assert_on_bound_origin()

    def set_input_files(self, selector: str, path: Path) -> None:
        self._assert_on_bound_origin()
        self._page.set_input_files(selector, str(path))
        self._assert_on_bound_origin()

    def click(self, selector: str) -> None:
        """Low-level primitive used only for revealing conditional
        sections (e.g. a "show more" toggle) — never for anything
        submit-shaped. `FormFiller`'s own public API deliberately does
        not expose a generic click passthrough; see that module's
        docstring for why the structural guarantee against a real submit
        lives at `submit()` itself, not here."""
        self._assert_on_bound_origin()
        self._page.click(selector)
        self._assert_on_bound_origin()  # a click can itself trigger navigation

    def click_submit_control(self, selector: str) -> None:
        """The ONE place in this class where a real submit-shaped click
        is an intended, named action rather than something structurally
        excluded — used ONLY by `job_agent.applications.browser.
        submit_control`'s deterministic, evidence-based control finder,
        after every safety check (approval validity, fresh security
        posture, unambiguous high-confidence control identification) has
        already passed. Mechanically identical to `click()`; kept as a
        separate, clearly-named method so a `grep` for "submit" finds
        every real submit-click site in this codebase, and so this one
        call site can never be confused with `click()`'s own
        conditional-section-reveal purpose."""
        self._assert_on_bound_origin()
        self._page.click(selector)
        self._assert_on_bound_origin()  # a submit click can itself trigger navigation

    def content(self) -> str:
        self._assert_on_bound_origin()
        return self._page.content()

    def visible_text(self) -> str:
        """Rendered, visible text only (never raw HTML source) — used by
        post-submit confirmation checks so a phrase sitting inside a
        hidden element, a `<script>` block, or an HTML comment can never
        count as evidence."""
        self._assert_on_bound_origin()
        return self._page.inner_text("body")

    def close(self) -> None:
        self._context.close()

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
