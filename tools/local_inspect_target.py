#!/usr/bin/env python3
"""Career Ops — READ-ONLY real-target inspection script.

Run this ON YOUR OWN MACHINE (not inside the restricted remote execution
environment) against a job application URL you have explicitly approved
for inspection.

WHAT THIS SCRIPT DOES, AND ONLY THIS:

    BrowserSession.load()
        -> ApplicationFormInspector.inspect()
            -> DynamicFieldMapper.to_questions()

It navigates to the target URL exactly once, reads the resulting DOM
structure using this repository's existing, unmodified production
inspection code, and prints a structured report. Nothing more.

WHAT THIS SCRIPT NEVER DOES:

  - fill any field (FormFiller is never imported)
  - plan or match answers (AnswerPlanner is never imported)
  - upload any file (FileUploadHandler is never imported)
  - authenticate, log in, or create an account
  - click the submit button or any button at all
  - call fill_application(), submit(), or verify()
  - modify this repository
  - read or use any real candidate data (CandidateProfile is never
    imported or constructed) -- this script only asks "what does this
    FORM look like", never "what would I put into it"

PRIVACY: this script never reads a form field's current DOM value. The
inspector classes it uses (DiscoveredField / ApplicationQuestion) don't
carry a "current value" field at all -- only labels, types, and required
flags, which describe the FORM, not any candidate's data. As a defensive
extra (in case a browser autofills something), each text-shaped field is
checked only for whether it is EMPTY or NON-EMPTY -- the actual value,
if any, is never read into this script or printed anywhere.

USAGE (run from a clone of this repository, on a machine with real
network access):

    pip install -e .
    playwright install chromium
    python tools/local_inspect_target.py "https://the-approved-url/apply"

Exits without modifying anything in the repository.
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/local_inspect_target.py <approved-url>", file=sys.stderr)
        return 2

    target_url = sys.argv[1]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed. Run:\n"
            "  pip install -e .\n"
            "  playwright install chromium\n"
            "then re-run this script.",
            file=sys.stderr,
        )
        return 2

    # Import ONLY the three production classes this checkpoint authorizes.
    # No FormFiller, no AnswerPlanner, no FileUploadHandler, no
    # BrowserApplicationProvider, no CandidateProfile -- this script
    # cannot fill, upload, submit, or touch candidate data even by
    # accident, because it never imports the code that could.
    from job_agent.applications.browser.field_mapper import DynamicFieldMapper
    from job_agent.applications.browser.inspector import ApplicationFormInspector
    from job_agent.applications.browser.session import BrowserSession, DomainDriftDetectedError

    print(f"Target (single navigation attempt): {target_url}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            session = BrowserSession(target_url, browser=browser)
            try:
                session.load()
            except DomainDriftDetectedError as exc:
                print("REDIRECT OFF ORIGIN DETECTED (session hard-stopped, as designed):")
                print(f"  {exc}")
                return 1
            except Exception as exc:  # noqa: BLE001 - report and stop, never retry
                print(f"LOAD FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1

            page = session.page  # read-only escape hatch; inspector uses this internally too
            final_url = session.current_url
            page_title = page.title()

            print("=== TARGET ===")
            print(f"final_url: {final_url}")
            print(f"page_title: {page_title}")

            def _attr(selector: str, attr: str) -> str | None:
                try:
                    return page.get_attribute(selector, attr)
                except Exception:  # noqa: BLE001
                    return None

            site_name_selector = 'meta[property="og:site_name"]'
            og_title_selector = 'meta[property="og:title"]'
            print(f"og:site_name: {_attr(site_name_selector, 'content')}")
            print(f"og:title: {_attr(og_title_selector, 'content')}")

            # --- ACCESS / SECURITY posture: structural presence counts only ---
            print("\n=== ACCESS / SECURITY ===")
            hidden_inputs = len(session.query_all('input[type="hidden"]'))
            password_inputs = len(session.query_all('input[type="password"]'))
            captcha_markers = len(
                session.query_all(".g-recaptcha, .h-captcha, [data-sitekey], #recaptcha, #captcha")
            )
            mfa_markers = len(session.query_all("[data-mfa], #mfa-challenge, .mfa-challenge"))
            external_auth_markers = len(
                session.query_all(
                    'a[href*="accounts.google.com"], a[href*="linkedin.com/oauth"], '
                    'button[class*="google"], button[class*="linkedin"], [class*="oauth"]'
                )
            )
            file_inputs = len(session.query_all('input[type="file"]'))
            form_count = len(session.query_all("form"))
            submit_like_selector = (
                'button[type="submit"], input[type="submit"], [class*="apply-btn"]'
            )
            submit_like = len(session.query_all(submit_like_selector))
            print(f"password_field_count: {password_inputs}")
            print(f"hidden_field_count: {hidden_inputs}")
            print(f"captcha_marker_count: {captcha_markers}")
            print(f"mfa_marker_count: {mfa_markers}")
            print(f"external_auth_marker_count: {external_auth_markers}")
            print(f"file_input_count: {file_inputs}")
            print(f"form_count: {form_count}")
            print(f"submit_like_control_count: {submit_like}")

            # --- FORM: the three authorized production calls ---
            inspection = ApplicationFormInspector().inspect(session)
            questions = DynamicFieldMapper().to_questions(inspection)

            print("\n=== INSPECTION (ApplicationFormInspector) ===")
            print(f"captcha_detected: {inspection.captcha_detected}")
            print(f"mfa_detected: {inspection.mfa_detected}")
            print(f"consent_fields: {list(inspection.consent_fields)}")
            print(f"field_count: {len(inspection.fields)}")

            print("\n=== DISCOVERED FIELDS ===")
            header = (
                f"{'field_id':<24} {'type':<12} {'required':<9} "
                f"{'visible':<8} {'empty?':<8} label"
            )
            print(header)
            for f in inspection.fields:
                empty_marker = "-"
                if f.visible and f.input_type in ("text", "textarea"):
                    try:
                        from job_agent.applications.browser.inspector import field_selector

                        el = session.query_all(field_selector(f.field_id))
                        if el:
                            # Presence-only check -- the actual value is
                            # never read into a variable that gets printed.
                            empty_marker = "empty" if not el[0].input_value() else "NON-EMPTY"
                    except Exception:  # noqa: BLE001
                        empty_marker = "?"
                print(
                    f"{f.field_id:<24} {f.input_type:<12} {str(f.required):<9} "
                    f"{str(f.visible):<8} {empty_marker:<8} {f.label}"
                )
                if f.options:
                    for opt in f.options:
                        print(f"    option: value={opt.value!r} text={opt.text!r}")

            print("\n=== QUESTIONS (DynamicFieldMapper.to_questions) ===")
            for q in questions:
                print(f"- [{q.category}] required={q.required}: {q.text}")

            print(
                "\nNOTE: no field value was read or printed above beyond an "
                "empty/non-empty presence check. No candidate data of any "
                "kind was used by this script."
            )
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
