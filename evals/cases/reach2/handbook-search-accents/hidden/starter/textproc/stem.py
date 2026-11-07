"""A deliberately light English stemmer.

Only the endings that cause most missed matches in the handbook are removed:
plurals, -ing and -ed. See docs/adr/0002-light-stemming.md for why this isn't
Porter or Snowball.
"""

from __future__ import annotations

_VOWELS = frozenset("aeiouy")
_KEEP_DOUBLE = frozenset("lsz")


def stem(term: str) -> str:
    """Strip one common English ending from a folded term."""
    if len(term) <= 3 or not term.isalpha():
        return term
    if term.endswith("sses"):
        return term[:-2]
    if term.endswith("ies") and len(term) > 4:
        return term[:-3] + "y"
    if term.endswith("ing") and len(term) > 5 and _has_vowel(term[:-3]):
        return _undouble(term[:-3])
    if term.endswith("ed") and len(term) > 4 and _has_vowel(term[:-2]):
        return _undouble(term[:-2])
    if term.endswith("s") and not term.endswith(("ss", "us", "is")):
        return term[:-1]
    return term


def _has_vowel(stem_part: str) -> bool:
    return any(ch in _VOWELS for ch in stem_part)


def _undouble(stem_part: str) -> str:
    """'running' -> 'runn' -> 'run', but 'billing' keeps its double l."""
    if len(stem_part) > 2 and stem_part[-1] == stem_part[-2] and stem_part[-1] not in _KEEP_DOUBLE:
        return stem_part[:-1]
    return stem_part
