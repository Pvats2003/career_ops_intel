"""Phase 6D — `ApplicationFormInspector`: reads structural facts out of a
loaded page's DOM. Never interprets, never decides consequences — exactly
the same "provider reports facts, core decides" boundary
`job_agent.applications.provider`'s module docstring establishes for
every other provider in this codebase. CAPTCHA/MFA detection here is
passive DOM inspection only (known marker attributes/classes) — this
module never attempts to load, render, solve, or evade a real
CAPTCHA/MFA challenge; it only reports that one is present.

FIELD DISCOVERY — two paths, always both active:

1. **Marked fields** (`[data-field]`) — the original Stage 1 mechanism.
   Explicit `data-field`/`data-label`/`data-required`/`data-consent`
   markers this project's own synthetic fixtures provide. Exact,
   unambiguous, zero heuristics. Still exactly how every existing fixture
   in `tests/fixtures/browser_provider/` is discovered — unchanged.

2. **Generic fields** (Stage 2 addition) — every `input`/`textarea`/
   `select` NOT already carrying `data-field` (so the two paths never
   double-discover the same element) is inspected using ordinary HTML
   semantics: an `id`/`name` attribute for identity, a `<label for>` /
   wrapping `<label>` / `aria-label` / `placeholder` for its label,
   radios grouped by shared `name` (not `id`, since that is how real
   HTML radio groups actually work), and the native `required` attribute
   — which the original `_is_required` already checked, so this needed
   no change. A field discoverable by neither an `id` nor a `name` is
   skipped rather than assigned an invented, unstable identifier — it
   cannot be reliably re-selected for filling anyway, and this module
   never guesses.

   This closes the gap the Phase 6D Stage 2 Drivetrain compatibility
   check identified: a real, third-party form's markup does not carry
   `data-field` attributes, so before this addition NOTHING on a real
   page would ever be discovered. It remains a heuristic, not a full DOM/
   accessibility-tree parser: it does not handle custom JS widget
   libraries masquerading as non-native controls, multi-step/paginated
   forms, or date-pickers. Label resolution can be wrong for unusual
   markup; when it cannot find anything, the field's own `id`/`name` is
   used as the label rather than leaving it blank — visibly present in
   the resulting `HumanReviewSnapshot` for a human to actually see it,
   never silently dropped.

   Consent detection for a generically-discovered checkbox is a
   conservative keyword heuristic over its resolved label
   (`_CONSENT_LABEL_KEYWORDS`) — deliberately biased toward false
   positives (an extra, safe `HUMAN_REQUIRED` stop) over false negatives
   (a real consent checkbox going unflagged). It is not a certainty, only
   a best-effort signal alongside the exact `data-consent` marker the
   marked-fields path already provides.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.applications.browser.session import BrowserSession

_CAPTCHA_SELECTORS = (
    ".g-recaptcha",
    ".h-captcha",
    "[data-sitekey]",
    "#recaptcha",
    "#captcha",
)
_MFA_SELECTORS = (
    "[data-mfa]",
    "#mfa-challenge",
    ".mfa-challenge",
)
_FIELD_SELECTOR = "[data-field]"

# Native form controls a generic-path query should consider — hidden/
# submit/button/reset/image inputs are never real, fillable "questions"
# and are deliberately excluded so this module never surfaces (or,
# elsewhere, fills) something shaped like a submit control.
_GENERIC_INPUT_EXCLUDED_TYPES = ("hidden", "submit", "button", "reset", "image")
_GENERIC_INPUT_SELECTOR = "input:not([data-field])" + "".join(
    f':not([type="{t}"])' for t in _GENERIC_INPUT_EXCLUDED_TYPES
)
_GENERIC_SELECTOR = ", ".join(
    [_GENERIC_INPUT_SELECTOR, "textarea:not([data-field])", "select:not([data-field])"]
)

_CONSENT_LABEL_KEYWORDS = (
    "consent", "agree", "terms", "privacy policy", "gdpr", "acknowledge",
)


@dataclass(frozen=True)
class DiscoveredOption:
    value: str
    text: str


@dataclass(frozen=True)
class DiscoveredField:
    """One field as currently observed in the live DOM — never a cached
    or assumed shape. `visible` distinguishes a field genuinely present
    right now from one a conditional section might reveal later; only
    currently-visible fields are ever filled (see `field_mapper.py`)."""

    field_id: str
    label: str
    input_type: str  # "text" | "textarea" | "select" | "multiselect" |
    # "radio" | "checkbox" | "file"
    required: bool
    visible: bool
    is_consent: bool = False
    options: tuple[DiscoveredOption, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class InspectionSnapshot:
    """Raw structural facts read from the DOM right now — this is what
    `ApplicationInspection` (the cross-provider schema type) gets built
    from; kept as a richer, provider-internal type here since the shared
    schema's `ApplicationInspection` only carries booleans/detail text."""

    fields: tuple[DiscoveredField, ...]
    captcha_detected: bool
    mfa_detected: bool
    consent_fields: tuple[str, ...]


class ApplicationFormInspector:
    """Stateless — takes an already-`load()`ed `BrowserSession` and reads
    its current DOM. Never navigates, never fills, never clicks anything
    beyond what `BrowserSession.query_all` itself does (read-only DOM
    queries)."""

    def inspect(self, session: BrowserSession) -> InspectionSnapshot:
        captcha_detected = self._any_present(session, _CAPTCHA_SELECTORS)
        mfa_detected = self._any_present(session, _MFA_SELECTORS)
        fields = self._discover_marked_fields(session) + self._discover_generic_fields(session)
        consent_fields = tuple(f.field_id for f in fields if f.is_consent)
        return InspectionSnapshot(
            fields=fields,
            captcha_detected=captcha_detected,
            mfa_detected=mfa_detected,
            consent_fields=consent_fields,
        )

    @staticmethod
    def _any_present(session: BrowserSession, selectors: tuple[str, ...]) -> bool:
        """A CAPTCHA/MFA marker only counts if it is actually VISIBLE right
        now — a real platform's placeholder can legitimately exist in the
        DOM but stay hidden until some other condition triggers it (exactly
        how the synthetic fixture's own scenario toggles work). Detecting
        by mere DOM presence would report a hidden marker as an active
        challenge, which is a false positive the safety gate must not act
        on."""
        for selector in selectors:
            for el in session.query_all(selector):
                if el.is_visible():
                    return True
        return False

    # ----------------------------------------------------------------
    # Path 1: explicit data-field markers (Stage 1, unchanged).
    # ----------------------------------------------------------------
    def _discover_marked_fields(self, session: BrowserSession) -> tuple[DiscoveredField, ...]:
        elements = session.query_all(_FIELD_SELECTOR)
        seen_radio_groups: set[str] = set()
        discovered: list[DiscoveredField] = []
        for el in elements:
            tag = (el.evaluate("e => e.tagName") or "").lower()
            input_type = (el.get_attribute("type") or "").lower()
            field_id = el.get_attribute("data-field") or ""
            if not field_id:
                continue

            if tag == "input" and input_type == "radio":
                if field_id in seen_radio_groups:
                    continue
                seen_radio_groups.add(field_id)
                options = self._marked_radio_options(session, field_id)
                discovered.append(
                    DiscoveredField(
                        field_id=field_id,
                        label=el.get_attribute("data-label") or "",
                        input_type="radio",
                        required=self._is_required(el),
                        visible=self._is_visible(el),
                        options=options,
                    )
                )
                continue

            discovered.append(
                DiscoveredField(
                    field_id=field_id,
                    label=el.get_attribute("data-label") or "",
                    input_type=self._resolve_input_type(tag, input_type, el),
                    required=self._is_required(el),
                    visible=self._is_visible(el),
                    is_consent=el.get_attribute("data-consent") == "true",
                    options=self._select_options(el) if tag == "select" else (),
                )
            )
        return tuple(discovered)

    @staticmethod
    def _marked_radio_options(
        session: BrowserSession, field_id: str
    ) -> tuple[DiscoveredOption, ...]:
        radios = session.query_all(f'input[type="radio"][data-field="{field_id}"]')
        options = []
        for r in radios:
            value = r.get_attribute("value") or ""
            # The synthetic fixture puts the human-readable option text in
            # a sibling data-option-label attribute on the same input.
            text = r.get_attribute("data-option-label") or value
            options.append(DiscoveredOption(value=value, text=text))
        return tuple(options)

    # ----------------------------------------------------------------
    # Path 2: generic real-world markup (Stage 2 addition). See module
    # docstring for the exact heuristic and its stated limitations.
    # ----------------------------------------------------------------
    def _discover_generic_fields(self, session: BrowserSession) -> tuple[DiscoveredField, ...]:
        elements = session.query_all(_GENERIC_SELECTOR)
        seen_radio_groups: set[str] = set()
        discovered: list[DiscoveredField] = []
        for el in elements:
            tag = (el.evaluate("e => e.tagName") or "").lower()
            input_type = (el.get_attribute("type") or "").lower()

            if tag == "input" and input_type == "radio":
                name = el.get_attribute("name") or ""
                if not name or name in seen_radio_groups:
                    continue
                seen_radio_groups.add(name)
                options = self._generic_radio_options(session, name)
                if not options:
                    continue
                discovered.append(
                    DiscoveredField(
                        field_id=name,
                        label=self._resolve_label(session, el),
                        input_type="radio",
                        required=self._is_required(el),
                        visible=self._is_visible(el),
                        options=options,
                    )
                )
                continue

            field_id = el.get_attribute("id") or el.get_attribute("name") or ""
            if not field_id:
                # No stable, re-selectable identifier — never invented,
                # this field is simply not discoverable yet.
                continue

            label = self._resolve_label(session, el)
            resolved_type = self._resolve_input_type(tag, input_type, el)
            discovered.append(
                DiscoveredField(
                    field_id=field_id,
                    label=label,
                    input_type=resolved_type,
                    required=self._is_required(el),
                    visible=self._is_visible(el),
                    is_consent=(
                        resolved_type == "checkbox" and self._looks_like_consent(label)
                    ),
                    options=self._select_options(el) if tag == "select" else (),
                )
            )
        return tuple(discovered)

    @staticmethod
    def _generic_radio_options(
        session: BrowserSession, name: str
    ) -> tuple[DiscoveredOption, ...]:
        radios = session.query_all(f'input[type="radio"][name="{name}"]')
        options = []
        for r in radios:
            value = r.get_attribute("value") or ""
            if not value:
                continue
            radio_id = r.get_attribute("id") or ""
            label = ""
            if radio_id:
                label_els = session.query_all(f'label[for="{radio_id}"]')
                if label_els:
                    label = (label_els[0].text_content() or "").strip()
            options.append(DiscoveredOption(value=value, text=label or value))
        return tuple(options)

    @staticmethod
    def _resolve_label(session: BrowserSession, el: object) -> str:
        """Ordinary HTML label-resolution, cheapest/most-certain first.
        Never fabricates — the final fallback is the element's own id/
        name, always visible to a human reviewing the resulting
        snapshot, never blank."""
        field_id = el.get_attribute("id") or ""  # type: ignore[attr-defined]
        if field_id:
            label_els = session.query_all(f'label[for="{field_id}"]')
            if label_els:
                text = (label_els[0].text_content() or "").strip()
                if text:
                    return text

        wrapping = el.evaluate(  # type: ignore[attr-defined]
            "e => { const l = e.closest('label'); return l ? l.textContent : ''; }"
        )
        if wrapping and wrapping.strip():
            return wrapping.strip()

        aria_label = el.get_attribute("aria-label") or ""  # type: ignore[attr-defined]
        if aria_label.strip():
            return aria_label.strip()

        placeholder = el.get_attribute("placeholder") or ""  # type: ignore[attr-defined]
        if placeholder.strip():
            return placeholder.strip()

        return field_id or (el.get_attribute("name") or "")  # type: ignore[attr-defined]

    @staticmethod
    def _looks_like_consent(label: str) -> bool:
        normalized = label.lower()
        return any(keyword in normalized for keyword in _CONSENT_LABEL_KEYWORDS)

    @staticmethod
    def _resolve_input_type(tag: str, input_type: str, el: object) -> str:
        if tag == "textarea":
            return "textarea"
        if tag == "select":
            is_multiple = el.evaluate("e => e.multiple")  # type: ignore[attr-defined]
            return "multiselect" if is_multiple else "select"
        if tag == "input" and input_type == "checkbox":
            return "checkbox"
        if tag == "input" and input_type == "file":
            return "file"
        return "text"

    @staticmethod
    def _select_options(el: object) -> tuple[DiscoveredOption, ...]:
        raw = el.evaluate(  # type: ignore[attr-defined]
            "e => Array.from(e.options).map(o => [o.value, o.textContent])"
        )
        return tuple(DiscoveredOption(value=v, text=t) for v, t in raw if v)

    @staticmethod
    def _is_required(el: object) -> bool:
        if el.get_attribute("data-required") == "true":  # type: ignore[attr-defined]
            return True
        return el.get_attribute("required") is not None  # type: ignore[attr-defined]

    @staticmethod
    def _is_visible(el: object) -> bool:
        return bool(el.is_visible())  # type: ignore[attr-defined]
