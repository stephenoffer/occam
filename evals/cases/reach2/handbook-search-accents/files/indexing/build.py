"""Building the index, re-reading only what changed.

`update` is what `findoc reindex` runs. A page whose digest matches its saved
entry keeps that entry; new and changed pages are read and tokenized; pages
that disappeared are dropped. `scan` builds the same thing in memory without
saving it, for searching a tree that has no index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from corpus import digest_of, iter_paths
from corpus.document import parse_document

from . import store
from .entry import Entry
from .store import Index


@dataclass
class BuildReport:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.changed) + len(self.reused)

    def summary(self) -> str:
        return (f"indexed {self.total} pages ({len(self.added)} added, {len(self.changed)} changed, "
                f"{len(self.reused)} unchanged, {len(self.removed)} removed)")


def collect(root: Path, previous: Optional[Index] = None) -> tuple[Index, BuildReport]:
    root = Path(root)
    old = previous.entries if previous is not None else {}
    entries: dict[str, Entry] = {}
    report = BuildReport()
    for path in iter_paths(root):
        data = (root / path).read_bytes()
        known = old.get(path)
        if known is not None and known.digest == digest_of(data):
            entries[path] = known
            report.reused.append(path)
            continue
        entries[path] = Entry.from_document(parse_document(path, data))
        (report.changed if known is not None else report.added).append(path)
    report.removed = sorted(set(old) - set(entries))
    return Index(entries), report


def update(root: Path, *, full: bool = False, now: Optional[datetime] = None) -> BuildReport:
    """Bring the saved index for root up to date and return what changed."""
    previous = None if full else store.load(root)
    index, report = collect(root, previous)
    index.built_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    store.save(root, index)
    return report


def scan(root: Path) -> Index:
    """Read every page under root into an index held only in memory."""
    return collect(root)[0]
