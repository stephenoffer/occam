"""Folding a word to the form that search compares.

Case is folded with str.casefold, so "Straße" and "STRASSE" compare equal, and
accents and other combining marks are removed, so "Café", "CAFE" and "cafe"
compare equal too. Apostrophes are dropped and punctuation at the edges of a
word is trimmed, so "don't", "dont" and "(dont)" are the same word. Everything
that turns text into terms goes through fold().
"""

from __future__ import annotations

import re
import unicodedata

_EDGES = re.compile(r"^[\W_]+|[\W_]+$")
_APOSTROPHES = str.maketrans("", "", "'’ʼ")


def strip_marks(text: str) -> str:
    """Remove accents and other combining marks: "Zürich" -> "Zurich"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold(word: str) -> str:
    """Return the folded form of one word, or "" when nothing word-like is left."""
    return _EDGES.sub("", strip_marks(word.translate(_APOSTROPHES).casefold()))
