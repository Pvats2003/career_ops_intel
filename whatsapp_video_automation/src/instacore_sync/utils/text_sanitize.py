"""Defenses against untrusted text reaching places where it can do more
than just be displayed.

Two concerns live here:

  * **Spreadsheet formula injection** (a well-known, OWASP-documented CSV/
    spreadsheet vulnerability class). `SheetsClient.upsert_row` writes cell
    values with the `USER_ENTERED` input option, which makes Google Sheets
    parse any value starting with `=`, `+`, `-`, or `@` as a formula. The
    video's filename is attacker-influenced: it comes from whatever a
    WhatsApp group member named the file before sending it, e.g.
    `=HYPERLINK("http://evil.example","click")_IC-188.mp4` — if written
    verbatim, the operator opening the sheet would see a clickable link
    with attacker-controlled text, or worse with formulas like
    `=IMPORTXML(...)` that can exfiltrate sheet contents to an external
    URL. Prefixing a lone leading apostrophe is the standard mitigation:
    Sheets (like Excel) treats a value with a leading `'` as forced literal
    text, never evaluating it as a formula, while the apostrophe itself is
    not displayed.

  * **Device ID validation** — a manually-entered Device ID (from the
    Needs Review screen) or a corrupted OCR read should never be trusted to
    be a safe, well-formed folder/sheet-cell value without checking it
    against the same pattern OCR extraction itself is held to.
"""

from __future__ import annotations

import re

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_for_spreadsheet_cell(value: str) -> str:
    """Neutralize formula injection in a value about to be written with
    Sheets' USER_ENTERED input option."""
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return f"'{value}"
    return value


def is_valid_device_id(device_id: str, pattern: str) -> bool:
    """True if `device_id` matches `pattern` in full (not just a substring).

    Used to guard Drive folder names / Sheet rows against a device ID that
    didn't come through the normal OCR-regex path — e.g. free text a user
    typed into the Needs Review screen's manual override field.
    """
    if not device_id:
        return False
    try:
        return re.fullmatch(pattern, device_id, re.IGNORECASE) is not None
    except re.error:
        return False
