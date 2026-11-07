"""Per-handbook settings from an optional `.findocrc` file at the root.

    [search]
    limit = 10
    snippet_width = 200
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from textproc.snippets import WIDTH

FILENAME = ".findocrc"


@dataclass(frozen=True)
class Settings:
    limit: int = 10
    snippet_width: int = WIDTH


def load(root: Path) -> Settings:
    parser = configparser.ConfigParser()
    try:
        parser.read_string((Path(root) / FILENAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except configparser.Error as error:
        raise SystemExit(f"findoc: can't read {FILENAME}: {error}") from error
    section = parser["search"] if parser.has_section("search") else {}
    defaults = Settings()
    return Settings(
        limit=_positive(section.get("limit"), defaults.limit, "limit"),
        snippet_width=_positive(section.get("snippet_width"), defaults.snippet_width, "snippet_width"),
    )


def _positive(raw, default: int, name: str) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"findoc: {FILENAME}: {name} must be a whole number, not {raw!r}") from None
    if value < 1:
        raise SystemExit(f"findoc: {FILENAME}: {name} must be at least 1")
    return value
