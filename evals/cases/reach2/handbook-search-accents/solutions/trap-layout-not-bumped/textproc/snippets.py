"""Showing where a page matched.

A snippet is a window of the page's original text, placed to contain as many of
the query's words as it can, with each occurrence wrapped in MARK. It works on
the text as written rather than on terms, so readers see the page as its author
wrote it. A query word matches, ignoring case and accents, at the start of a
word in the text, so "laptop" also marks "laptops" and "cafe" marks "Café".
Matching runs on a folded copy of the text, and each match is mapped back to
the original characters before it is marked.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Pattern

from .normalize import strip_marks

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


def _comparable(text: str) -> tuple[str, list[int]]:
    """Fold text for matching, and say where in text each folded character came from.

    One original character can fold to several ("ß" to "ss") or to none (a
    combining accent), so positions are kept per folded character, plus one
    past the end.
    """
    folded: list[str] = []
    origin: list[int] = []
    for position, character in enumerate(text):
        for part in strip_marks(character.casefold()):
            folded.append(part)
            origin.append(position)
    origin.append(len(text))
    return "".join(folded), origin


def _pattern(query_words: Iterable[str]) -> Optional[Pattern[str]]:
    folded = {strip_marks(word.casefold()) for word in query_words}
    alternatives = sorted((re.escape(word) for word in folded if word), key=len, reverse=True)
    if not alternatives:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")\w*")


def find_matches(text: str, query_words: Iterable[str]) -> list[tuple[int, int]]:
    """Return the (start, end) in text of every occurrence of a query word."""
    pattern = _pattern(query_words)
    if pattern is None:
        return []
    folded, origin = _comparable(text)
    return [(origin[match.start()], origin[match.end()]) for match in pattern.finditer(folded)]


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
