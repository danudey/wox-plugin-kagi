"""Small text helpers shared by the query handlers."""

from __future__ import annotations

import html
import re
from typing import Tuple

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_LANGUAGE_SUFFIX_RE = re.compile(r"\s*>\s*([A-Za-z]{2,3}(?:[-_][A-Za-z]{2,4})?)\s*$")
_URL_RE = re.compile(r"^(?:https?://|www\.)\S+$|^[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", re.IGNORECASE)


def clean_snippet(snippet: str) -> str:
    """Strip the markup Kagi puts around matched terms and collapse whitespace."""

    if not snippet:
        return ""

    return _WHITESPACE_RE.sub(" ", html.unescape(_TAG_RE.sub("", snippet))).strip()


def quoted(text: str) -> str:
    return f"“{text}”"


def looks_like_url(text: str) -> bool:
    """True when the text should be handed to the summarizer as a URL."""

    text = text.strip()
    return bool(text) and " " not in text and bool(_URL_RE.match(text))


def parse_language_suffix(text: str, default: str) -> Tuple[str, str]:
    """Split a trailing ``> lang`` override off the text.

    ``"hello world > fr"`` becomes ``("hello world", "fr")``.
    """

    match = _LANGUAGE_SUFFIX_RE.search(text)
    if not match:
        return text.strip(), default

    return text[: match.start()].strip(), match.group(1).lower()


def format_published(published: str) -> str:
    """Reduce an ISO timestamp to a plain date, leaving anything else alone."""

    published = (published or "").strip()
    if not published:
        return ""

    match = re.match(r"^(\d{4}-\d{2}-\d{2})", published)
    return match.group(1) if match else published[:24]


def summary_subtitle(output: str, limit: int = 120) -> str:
    """First line of a generated answer, trimmed to fit a result title."""

    first_line = _WHITESPACE_RE.sub(" ", output.strip())
    if len(first_line) <= limit:
        return first_line

    return first_line[: limit - 1].rstrip() + "…"
