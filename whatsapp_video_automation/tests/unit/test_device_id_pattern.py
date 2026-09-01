"""Regression tests for the Device ID regex boundary fix.

The original pattern `IC-\\d{1,5}` had no boundary assertions, so a plain
`re.search` would false-positive match the literal substring "IC-188"
inside words like "MAGIC-188" or "GENERIC-23" — a realistic OCR misread of
surrounding UI chrome that happens to end in "...IC-<digits>". The fixed
pattern requires the match to be a standalone token.
"""

from __future__ import annotations

import re

from instacore_sync.core.constants import DEVICE_ID_REGEX_DEFAULT

_PATTERN = re.compile(DEVICE_ID_REGEX_DEFAULT, re.IGNORECASE)


def test_matches_standalone_device_id() -> None:
    match = _PATTERN.search("Device: IC-188")
    assert match is not None
    assert match.group(0) == "IC-188"


def test_matches_at_start_of_string() -> None:
    assert _PATTERN.search("IC-551 connected") is not None


def test_rejects_false_positive_word_ending_in_ic() -> None:
    # "MAGIC-188" literally contains the substring "IC-188" — the fix must
    # not match it, since there is no real Device ID here.
    assert _PATTERN.search("MAGIC-188 status") is None


def test_rejects_false_positive_generic_word() -> None:
    assert _PATTERN.search("GENERIC-23 mode enabled") is None


def test_rejects_false_positive_topic_word() -> None:
    assert _PATTERN.search("TOPIC-5 selected") is None


def test_rejects_partial_number_match() -> None:
    # "IC-1888" should not be read as "IC-188" with a trailing "8" — the
    # lookahead must prevent matching a shorter prefix of a longer number.
    match = _PATTERN.search("IC-1888")
    assert match is not None
    assert match.group(0) == "IC-1888"  # matches the whole number, not a truncated prefix


def test_case_insensitive_match_still_works() -> None:
    assert _PATTERN.search("ic-83") is not None
