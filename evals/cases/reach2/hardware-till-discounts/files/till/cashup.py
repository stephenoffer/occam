"""The end-of-day cash-up (the "Z read").

The manager counts the drawer and the cash-up says what should be in it: the opening float, plus
cash taken, minus change given. Card is settled by the card terminal's own end-of-day and is only
listed here. Sales are shown by department so the manager can spot a mis-keyed line before the
day is closed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from catalog.departments import department_name
from till import journal
from till.money import fmt
from till.settings import load_settings


@dataclass
class CashUp:
    store: str
    till: int
    day: date
    float_pence: int
    sales_count: int = 0
    sales_total_pence: int = 0
    departments: Counter = field(default_factory=Counter)
    tenders: Counter = field(default_factory=Counter)
    change_pence: int = 0
    counted_cash_pence: int | None = None

    @property
    def expected_cash_pence(self) -> int:
        return self.float_pence + self.tenders["cash"] - self.change_pence

    @property
    def variance_pence(self) -> int | None:
        if self.counted_cash_pence is None:
            return None
        return self.counted_cash_pence - self.expected_cash_pence

    @property
    def paid_pence(self) -> int:
        """What customers actually paid: everything tendered less the change handed back."""
        return sum(self.tenders.values()) - self.change_pence


def cash_up(data_dir: Path, day: date, counted_cash_pence: int | None = None) -> CashUp:
    settings = load_settings(data_dir)
    result = CashUp(settings.store, settings.number, day, settings.float_pence, counted_cash_pence=counted_cash_pence)
    for sale in journal.read_day(data_dir, day):
        result.sales_count += 1
        result.sales_total_pence += sale.total_pence
        for line in sale.lines:
            result.departments[line.department] += line.total_pence
        for tender in sale.tenders:
            result.tenders[tender.type] += tender.pence
        result.change_pence += sale.change_pence
    return result


def as_json(result: CashUp) -> dict:
    return {
        "store": result.store,
        "till": result.till,
        "date": result.day.isoformat(),
        "sales_count": result.sales_count,
        "sales_total_pence": result.sales_total_pence,
        "departments": dict(sorted(result.departments.items())),
        "tenders": dict(sorted(result.tenders.items())),
        "change_pence": result.change_pence,
        "float_pence": result.float_pence,
        "expected_cash_pence": result.expected_cash_pence,
        "counted_cash_pence": result.counted_cash_pence,
        "variance_pence": result.variance_pence,
    }


def _row(label: str, amount: str, width: int = 40) -> str:
    return f"{label:<{width - 12}}{amount:>12}"


def render(result: CashUp) -> str:
    rows = [f"CASH-UP {result.store} till {result.till} {result.day.isoformat()}", ""]
    rows.append(_row(f"Sales ({result.sales_count})", fmt(result.sales_total_pence)))
    for code, pence in sorted(result.departments.items()):
        rows.append(_row(f"  {code} {department_name(code)}", fmt(pence)))
    rows.append("")
    rows.append("Tenders")
    for kind, pence in sorted(result.tenders.items()):
        rows.append(_row(f"  {kind}", fmt(pence)))
    rows.append(_row("Change given", fmt(result.change_pence)))
    rows.append("")
    rows.append(_row("Float", fmt(result.float_pence)))
    rows.append(_row("Expected cash in drawer", fmt(result.expected_cash_pence)))
    if result.counted_cash_pence is not None:
        rows.append(_row("Counted cash", fmt(result.counted_cash_pence)))
        rows.append(_row("Over (+) / short (-)", fmt(result.variance_pence)))
    if result.paid_pence != result.sales_total_pence:
        rows.append("")
        rows.append(f"WARNING: payments {fmt(result.paid_pence)} don't match sales {fmt(result.sales_total_pence)}")
    return "\n".join(rows) + "\n"
