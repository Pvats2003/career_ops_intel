"""Phase 6D Stage 1 — `ApplicationFormInspector`: reads structural facts
out of a loaded page's DOM. Never interprets, never decides consequences
— exactly the same "provider reports facts, core decides" boundary
`job_agent.applications.provider`'s module docstring establishes for
every other provider in this codebase. CAPTCHA/MFA detection here is
passive DOM inspection only (known marker attributes/classes) — this
module never attempts to load, render, solve, or evade a real
CAPTCHA/MFA challenge; it only reports that one is present.

STAGE 1 SCOPE, STATED PLAINLY: this inspector recognizes fields via
explicit `data-field`/`data-label`/`data-required` markers the local
synthetic fixture site provides — it does not (yet) implement the
general heuristic DOM analysis (matching a `<label>` to its nearest
input, inferring structure from arbitrary real-world markup) a genuinely
third-party real form would need. That generalization gap is real and
deliberate; see the Phase 6D design proposal's Stage 2 discussion for why
it is not attempted here.
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
_CONSENT_SELECTOR = "[data-consent]"
_FIELD_SELECTOR = "[data-field]"


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
        fields = self._discover_fields(session)
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

    def _discover_fields(self, session: BrowserSession) -> tuple[DiscoveredField, ...]:
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
                options = self._radio_options(session, field_id)
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
    def _radio_options(session: BrowserSession, field_id: str) -> tuple[DiscoveredOption, ...]:
        radios = session.query_all(f'input[type="radio"][data-field="{field_id}"]')
        options = []
        for r in radios:
            value = r.get_attribute("value") or ""
            # The synthetic fixture puts the human-readable option text in
            # a sibling data-option-label attribute on the same input.
            text = r.get_attribute("data-option-label") or value
            options.append(DiscoveredOption(value=value, text=text))
        return tuple(options)

    @staticmethod
    def _is_required(el: object) -> bool:
        if el.get_attribute("data-required") == "true":  # type: ignore[attr-defined]
            return True
        return el.get_attribute("required") is not None  # type: ignore[attr-defined]

    @staticmethod
    def _is_visible(el: object) -> bool:
        return bool(el.is_visible())  # type: ignore[attr-defined]
