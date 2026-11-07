"""Site names and regions for forecast reports, from data/sites.csv."""

from __future__ import annotations

from pathlib import Path

from common.csvio import read_rows


def load_site_names(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    return {row["site"]: row["name"] for row in read_rows(path, ["site", "name"])}


def label(site: str, names: dict[str, str]) -> str:
    return names.get(site, site)
