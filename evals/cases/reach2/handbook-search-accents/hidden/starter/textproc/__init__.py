"""Turning text into search terms, and showing where a page matched."""

from .normalize import fold
from .terms import term, terms, words

__all__ = ["fold", "term", "terms", "words"]
