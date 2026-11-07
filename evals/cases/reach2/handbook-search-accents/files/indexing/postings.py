"""Turning per-page term counts around: for each term, the pages that contain it."""

from __future__ import annotations

from typing import Mapping

from .entry import Entry


def invert(entries: Mapping[str, Entry]) -> dict[str, dict[str, int]]:
    """term -> {path: count}."""
    inverted: dict[str, dict[str, int]] = {}
    for path, entry in entries.items():
        for term, count in entry.counts.items():
            inverted.setdefault(term, {})[path] = count
    return inverted


def document_frequencies(inverted: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    return {term: len(pages) for term, pages in inverted.items()}


def average_length(entries: Mapping[str, Entry]) -> float:
    if not entries:
        return 0.0
    return sum(entry.length for entry in entries.values()) / len(entries)
