"""Showing where a page matched.

A snippet is a window of the page's original text, placed to contain as many of
the query's words as it can, with each occurrence wrapped in MARK. It works on
the text as written rather than on terms, so readers see the page as its author
wrote it. A query word matches, ignoring case, at the start of a word in the
text, so "laptop" also marks "laptops".
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Pattern

MARK = "**"
WIDTH = 200
ELLIPSIS = "…"
LEAD_IN = 40

_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_EMPHASIS = re.compile(r"[*`]+")


def plain(markdown: str) -> str:
    """Reduce markdown to plain running text: no heading markers, emphasis or link targets."""
    text = _LINK.sub(r"\1", markdown)
    text = _HEADING.sub("", text)
    text = _EMPHASIS.sub("", text)
    return " ".join(text.split())


def _pattern(query_words: Iterable[str]) -> Optional[Pattern[str]]:
    alternatives = sorted({re.escape(word) for word in query_words if word}, key=len, reverse=True)
    if not alternatives:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")\w*", re.IGNORECASE)


def find_matches(text: str, query_words: Iterable[str]) -> list[tuple[int, int]]:
    """Return the (start, end) of every occurrence of a query word in text."""
    pattern = _pattern(query_words)
    if pattern is None:
        return []
    return [match.span() for match in pattern.finditer(text)]


def _best_start(spans: list[tuple[int, int]], width: int) -> int:
    best_start, best_count = 0, 0
    for index, (start, _) in enumerate(spans):
        count = sum(1 for other, _ in spans[index:] if other < start + width - LEAD_IN)
        if count > best_count:
            best_start, best_count = start, count
    return best_start


def snippet(markdown: str, query_words: Iterable[str], width: int = WIDTH) -> str:
    """Return a window of the page with the query's words marked."""
    text = plain(markdown)
    spans = find_matches(text, query_words)
    start = max(0, _best_start(spans, width) - LEAD_IN) if spans else 0
    if start > 0:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < start + LEAD_IN else start
    end = min(len(text), start + width)
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start else end
    pieces, cursor = [], start
    for match_start, match_end in spans:
        if match_start < start or match_end > end:
            continue
        pieces.append(text[cursor:match_start])
        pieces.append(MARK + text[match_start:match_end] + MARK)
        cursor = match_end
    pieces.append(text[cursor:end])
    prefix = ELLIPSIS if start > 0 else ""
    suffix = ELLIPSIS if end < len(text) else ""
    return prefix + "".join(pieces).strip() + suffix
