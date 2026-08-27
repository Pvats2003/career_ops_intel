"""Shared HTML-to-text helper for ATS sources that return job descriptions
as HTML fragments (Greenhouse's `content` field, Lever's `descriptionHtml`)."""

from __future__ import annotations

from bs4 import BeautifulSoup


def html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line) or None
