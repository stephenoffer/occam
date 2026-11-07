"""Shared bits for the till tests."""

from __future__ import annotations

import json
from pathlib import Path

from catalog.products import load_catalog

CATALOG = load_catalog()


def write_settings(data_dir: Path, store: str = "BRH01", number: int = 1, float_pence: int = 10000) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "till.ini").write_text(
        f"[till]\nstore = {store}\nstore_name = Brindle Test\nnumber = {number}\nfloat_pence = {float_pence}\n",
        encoding="utf-8",
    )


def basket(at: str, lines: list[dict], tenders: list[dict]) -> dict:
    return {"at": at, "lines": lines, "tenders": tenders}


def write_basket(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
