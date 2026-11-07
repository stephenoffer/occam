"""Listing the pages under a handbook root, in a stable order."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from .ignore import IgnoreRules

SUFFIXES = (".md", ".markdown", ".txt")


def iter_paths(root: Path) -> Iterator[str]:
    """Yield every searchable page under root as a relative posix path.

    Hidden directories (including `.git`) are skipped, as is anything
    `.findocignore` excludes.
    """
    root = Path(root)
    rules = IgnoreRules.for_root(root)
    for directory, subdirectories, filenames in os.walk(root):
        relative_dir = Path(directory).relative_to(root).as_posix()
        relative_dir = "" if relative_dir == "." else relative_dir
        subdirectories[:] = sorted(
            name for name in subdirectories
            if not name.startswith(".") and not rules.ignores_directory(_join(relative_dir, name))
        )
        for name in sorted(filenames):
            relative = _join(relative_dir, name)
            if name.startswith(".") or not name.lower().endswith(SUFFIXES) or rules.ignores_file(relative):
                continue
            yield relative


def _join(directory: str, name: str) -> str:
    return f"{directory}/{name}" if directory else name
