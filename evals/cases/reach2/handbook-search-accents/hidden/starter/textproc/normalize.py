"""Folding a word to the form that search compares.

Case is folded with str.casefold, so "Straße" and "STRASSE" compare equal.
Apostrophes are dropped and punctuation at the edges of a word is trimmed, so
"don't", "dont" and "(dont)" are the same word. Everything that turns text into
terms goes through fold().
"""

from __future__ import annotations

import re

_EDGES = re.compile(r"^[\W_]+|[\W_]+$")
_APOSTROPHES = str.maketrans("", "", "'’ʼ")


def fold(word: str) -> str:
    """Return the folded form of one word, or "" when nothing word-like is left."""
    return _EDGES.sub("", word.translate(_APOSTROPHES).casefold())
