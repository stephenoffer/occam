"""Reading and writing the CSV exports we trade with the site app and the bureau."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


class CsvError(ValueError):
    pass


def read_rows(path: str | Path, required: Iterable[str]) -> list[dict[str, str]]:
    """Rows as dicts with surrounding whitespace removed. Blank lines and ``#`` comment lines are skipped."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        reader = csv.DictReader(lines)
        if reader.fieldnames is None:
            raise CsvError(f"{path}: empty file")
        header = [name.strip() for name in reader.fieldnames]
        missing = [name for name in required if name not in header]
        if missing:
            raise CsvError(f"{path}: missing columns {', '.join(missing)}")
        rows = []
        for number, row in enumerate(reader, start=2):
            clean = {key.strip(): (value or "").strip() for key, value in row.items() if key is not None}
            clean["_line"] = str(number)
            rows.append(clean)
        return rows


def write_rows(path: str | Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
