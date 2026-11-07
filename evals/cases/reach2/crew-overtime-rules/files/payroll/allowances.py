"""Remote-site allowances: a flat amount per approved shift at sites that pay one.

The amounts live in data/sites.csv (column remote_allowance). Sites with no amount pay none.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from common.csvio import read_rows
from common.money import parse_money
from timesheets.models import Shift


def load_site_allowances(path: str | Path) -> dict[str, Decimal]:
    allowances = {}
    for row in read_rows(path, ["site", "name"]):
        amount = row.get("remote_allowance", "")
        if amount:
            allowances[row["site"]] = parse_money(amount)
    return allowances


def allowance_for(worker_id: str, shifts: Iterable[Shift], allowances: dict[str, Decimal]) -> Decimal:
    counts = Counter(s.site for s in shifts if s.worker_id == worker_id and s.approved)
    return sum((allowances.get(site, Decimal(0)) * n for site, n in counts.items()), Decimal(0))
