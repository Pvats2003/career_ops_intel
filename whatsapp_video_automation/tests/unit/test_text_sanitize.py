from __future__ import annotations

import pytest

from instacore_sync.core.constants import DEVICE_ID_REGEX_DEFAULT
from instacore_sync.utils.text_sanitize import is_valid_device_id, sanitize_for_spreadsheet_cell


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=HYPERLINK(\"http://evil.example\")", "'=HYPERLINK(\"http://evil.example\")"),
        ("+1+1", "'+1+1"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("normal_filename.mp4", "normal_filename.mp4"),
        ("IC-188_clip.mp4", "IC-188_clip.mp4"),
        ("", ""),
    ],
)
def test_sanitize_for_spreadsheet_cell(raw: str, expected: str) -> None:
    assert sanitize_for_spreadsheet_cell(raw) == expected


@pytest.mark.parametrize(
    "device_id,expected",
    [
        ("IC-188", True),
        ("ic-551", True),
        ("IC-23", True),
        ("", False),
        ("not-an-id", False),
        ("../../etc/passwd", False),
        ("=cmd|'/c calc'!A0", False),
        ("MAGIC-188", False),  # the same false-positive substring case the regex fix targets
    ],
)
def test_is_valid_device_id(device_id: str, expected: bool) -> None:
    assert is_valid_device_id(device_id, DEVICE_ID_REGEX_DEFAULT) is expected


def test_is_valid_device_id_handles_bad_pattern_gracefully() -> None:
    assert is_valid_device_id("IC-188", "[unterminated") is False
