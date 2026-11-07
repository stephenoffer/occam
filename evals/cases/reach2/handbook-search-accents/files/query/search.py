"""Running a search against a handbook root.

Search uses the saved index when the root has a usable one, and otherwise
reads every page itself, which is fine for a small tree and slow for the full
handbook. It never writes anything; only `findoc reindex` does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from corpus import read_document
from indexing import build, store
from indexing.postings import average_length, document_frequencies, invert
from indexing.store import Index
from textproc import terms
from textproc.snippets import WIDTH, snippet

from .parse import Query, parse
from .rank import score


@dataclass(frozen=True)
class Hit:
    path: str
    title: str
    owner: str
    score: float
    snippet: str


def open_index(root: Path) -> tuple[Index, bool]:
    """Return (index, saved): the saved index if usable, else one built in memory."""
    saved = store.load(root)
    if saved is not None:
        return saved, True
    return build.scan(root), False


def search(root: Path, text: str, *, limit: int = 10, width: int = WIDTH,
           index: Optional[Index] = None) -> list[Hit]:
    root = Path(root)
    query = parse(text)
    if query.is_empty:
        return []
    if index is None:
        index, _ = open_index(root)
    inverted = invert(index.entries)
    candidates = set(index.entries)
    for required in query.required:
        candidates &= set(inverted.get(required, {}))
    for excluded in query.excluded:
        candidates -= set(inverted.get(excluded, {}))
    if query.tags:
        candidates = {path for path in candidates if set(query.tags) <= set(index.entries[path].tags)}
    if query.title_terms:
        candidates = {path for path in candidates
                      if set(query.title_terms) <= set(index.entries[path].title_terms)}

    frequencies = document_frequencies(inverted)
    average = average_length(index.entries)
    ranked = sorted(
        ((score(index.entries[path], query.required + query.title_terms, frequencies, len(index.entries), average), path)
         for path in candidates),
        key=lambda pair: (-pair[0], pair[1]),
    )
    hits: list[Hit] = []
    for value, path in ranked:
        hit = _hit(root, path, value, query, width, index)
        if hit is not None:
            hits.append(hit)
        if len(hits) >= limit:
            break
    return hits


def _hit(root: Path, path: str, value: float, query: Query, width: int, index: Index) -> Optional[Hit]:
    try:
        document = read_document(root, path)
    except FileNotFoundError:
        return None  # deleted since the index was written
    if query.phrases and not all(_contains(terms(document.title) + terms(document.body), phrase)
                                 for phrase in query.phrases):
        return None
    entry = index.entries[path]
    return Hit(path=path, title=entry.title, owner=entry.owner, score=round(value, 4),
               snippet=snippet(document.body, query.highlight, width))


def _contains(sequence: list[str], phrase: list[str]) -> bool:
    size = len(phrase)
    return any(sequence[start:start + size] == phrase for start in range(len(sequence) - size + 1))
