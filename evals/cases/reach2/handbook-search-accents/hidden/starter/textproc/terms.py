"""Splitting text into search terms.

A term is a word after folding and stemming, with stopwords dropped. Pages and
queries are split the same way, which is what lets "Laptops" in a page match a
search for "laptop".
"""

from __future__ import annotations

import re
from typing import Iterator, Optional

from .normalize import fold
from .stem import stem
from .stopwords import STOPWORDS

WORD = re.compile(r"[\w'’ʼ]+")


def words(text: str) -> Iterator[str]:
    """Yield the words of text as written."""
    for match in WORD.finditer(text):
        yield match.group()


def term(word: str) -> Optional[str]:
    """Return the term for one word, or None if it doesn't count (stopword, punctuation)."""
    folded = fold(word)
    if not folded or folded in STOPWORDS:
        return None
    return stem(folded)


def terms(text: str) -> list[str]:
    """Return the terms of text, in order, repeats included."""
    found = []
    for word in words(text):
        value = term(word)
        if value is not None:
            found.append(value)
    return found
