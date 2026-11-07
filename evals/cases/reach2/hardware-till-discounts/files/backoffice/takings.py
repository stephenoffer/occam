"""A store's takings for a trading day, worked out from its tape.

Takings are what finance posts: sales by department, and how the money came in. Two cross-checks
run on every sale, because a tape that disagrees with itself is the first sign of a till fault:
the lines on a sale must come to what the customer paid (tendered less change), and a sale may
only appear once. Sales that fail either check are listed as mismatches; they're still counted, and
someone in finance looks at them before the day is posted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from backoffice.inbox import tapes_for_day
from backoffice.tapes import Quarantined, read_tape


@dataclass
class StoreTakings:
    store: str
    day: date
    sales_count: int = 0
    sales_pence: int = 0
    departments: Counter = field(default_factory=Counter)
    tenders: Counter = field(default_factory=Counter)
    change_pence: int = 0
    mismatches: list[str] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)

    @property
    def banked_cash_pence(self) -> int:
        return self.tenders["cash"] - self.change_pence


def takings_for_day(inbox: Path, day: date) -> dict[str, StoreTakings]:
    result: dict[str, StoreTakings] = {}
    for path in tapes_for_day(inbox, day):
        tape = read_tape(path)
        takings = result.setdefault(tape.store, StoreTakings(tape.store, day))
        takings.quarantined.extend(tape.quarantined)
        seen: set[str] = set()
        for sale in tape.sales:
            takings.sales_count += 1
            takings.sales_pence += sale.line_total
            for line in sale.lines:
                takings.departments[line.dept] += line.amount
            for kind, pence in sale.tenders.items():
                takings.tenders[kind] += pence
            takings.change_pence += sale.change
            if sale.line_total != sale.paid or sale.sale in seen:
                takings.mismatches.append(sale.sale)
            seen.add(sale.sale)
    return result


def as_json(takings: dict[str, StoreTakings]) -> dict:
    stores = {}
    for store, t in sorted(takings.items()):
        stores[store] = {
            "sales_count": t.sales_count,
            "sales_pence": t.sales_pence,
            "departments": dict(sorted(t.departments.items())),
            "tenders": dict(sorted(t.tenders.items())),
            "change_pence": t.change_pence,
            "banked_cash_pence": t.banked_cash_pence,
            "mismatches": list(t.mismatches),
            "quarantined": [{"tape": q.tape, "line": q.line_no, "reason": q.reason} for q in t.quarantined],
        }
    return {"stores": stores}
