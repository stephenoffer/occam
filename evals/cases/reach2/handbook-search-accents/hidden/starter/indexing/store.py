"""The index file kept at `<root>/.findoc/index.json`.

It records, for every page, the terms textproc produced for it when the page
was last read, alongside the page's digest so that `reindex` can skip pages
that haven't changed. Those entries are reused exactly as they were written,
so stored terms are only as current as the code that produced them: anything
that changes the terms stored for a page (splitting, folding, stemming,
stopwords) needs a new LAYOUT, otherwise old indexes keep serving old terms.

An index whose layout isn't LAYOUT, or that can't be read, is treated as
absent: search falls back to reading the pages, and the next `reindex` writes
a complete new one.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .entry import Entry

LAYOUT = 3
DIRECTORY = ".findoc"
FILENAME = "index.json"


@dataclass
class Index:
    entries: dict[str, Entry] = field(default_factory=dict)
    built_at: Optional[str] = None

    def __len__(self) -> int:
        return len(self.entries)


def path_for(root: Path) -> Path:
    return Path(root) / DIRECTORY / FILENAME


def load(root: Path) -> Optional[Index]:
    """Return the saved index for root, or None if there is no usable one."""
    try:
        raw = json.loads(path_for(root).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("layout") != LAYOUT:
        return None
    try:
        entries = {path: Entry.from_json(data) for path, data in raw["documents"].items()}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return Index(entries, raw.get("built_at"))


def save(root: Path, index: Index) -> Path:
    """Write the index atomically, so a search running at the same time never sees half a file."""
    target = path_for(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layout": LAYOUT,
        "built_at": index.built_at,
        "documents": {path: entry.to_json() for path, entry in sorted(index.entries.items())},
    }
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".index-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target
