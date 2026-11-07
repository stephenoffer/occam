"""Building tapes for the head office tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixtures(inbox: Path) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    for path in FIXTURES.glob("*.tape"):
        shutil.copy(path, inbox / path.name)
    return inbox


def record(store="BRH01", sale="BRH01-1-261109-0001", at="2026-11-09T09:00:00", lines=None, tenders=None, change=0, **extra):
    data = {"v": 2, "store": store, "till": 1, "sale": sale, "at": at,
            "lines": lines if lines is not None else [{"sku": "PLB-PTFE", "dept": "PLB", "qty": 1, "unit": 99}],
            "tenders": tenders if tenders is not None else [{"type": "cash", "pence": 99}], "change": change}
    data.update(extra)
    return data


def write_tape(inbox: Path, name: str, records: list) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records), encoding="utf-8")
    return path
