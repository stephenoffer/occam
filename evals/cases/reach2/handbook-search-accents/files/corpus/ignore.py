"""`.findocignore`: pages that exist in the tree but shouldn't be searchable.

One glob pattern per line, matched against the path relative to the root.
A pattern ending in `/` matches a directory and everything under it. Blank
lines and lines starting with `#` are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

IGNORE_FILE = ".findocignore"


@dataclass(frozen=True)
class IgnoreRules:
    files: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "IgnoreRules":
        files, directories = [], []
        for line in text.splitlines():
            pattern = line.strip()
            if not pattern or pattern.startswith("#"):
                continue
            if pattern.endswith("/"):
                directories.append(pattern.rstrip("/"))
            else:
                files.append(pattern)
        return cls(tuple(files), tuple(directories))

    @classmethod
    def for_root(cls, root: Path) -> "IgnoreRules":
        try:
            return cls.parse((Path(root) / IGNORE_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()

    def ignores_directory(self, relative: str) -> bool:
        return any(fnmatchcase(relative, pattern) or fnmatchcase(PurePosixPath(relative).name, pattern)
                   for pattern in self.directories)

    def ignores_file(self, relative: str) -> bool:
        name = PurePosixPath(relative).name
        return any(fnmatchcase(relative, pattern) or fnmatchcase(name, pattern) for pattern in self.files)
