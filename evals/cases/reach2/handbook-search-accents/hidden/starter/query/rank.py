"""Okapi BM25 with a boost for terms that appear in a page's title.

The constants are the textbook defaults; tuning them against the handbook made
no difference anyone could see (docs/adr/0001-json-index-on-disk.md has the
numbers from when that was tried).
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping

from indexing.entry import Entry

K1 = 1.2
B = 0.75
TITLE_BOOST = 1.5


def idf(document_frequency: int, page_count: int) -> float:
    return math.log(1 + (page_count - document_frequency + 0.5) / (document_frequency + 0.5))


def score(entry: Entry, query_terms: Iterable[str], frequencies: Mapping[str, int], page_count: int,
          average_length: float) -> float:
    total = 0.0
    length_factor = 1 - B + B * (entry.length / average_length if average_length else 1.0)
    for query_term in query_terms:
        count = entry.counts.get(query_term, 0)
        if not count:
            continue
        weight = idf(frequencies.get(query_term, 0), page_count)
        part = weight * count * (K1 + 1) / (count + K1 * length_factor)
        if query_term in entry.title_terms:
            part *= TITLE_BOOST
        total += part
    return total
