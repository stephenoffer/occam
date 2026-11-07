"""Journal lines for the accounting system: debit wages per cost centre, credit accrued wages.

The import file is the finance system's generic journal CSV. Reversal on the first of the next
month is set up in the finance system, not here.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from common.csvio import write_rows
from common.money import plain

WAGES_ACCOUNT = "5100"
ACCRUED_WAGES_ACCOUNT = "2210"
FIELDS = ["account", "cost_centre", "debit", "credit", "narrative"]


def journal_lines(month: str, accrued: dict[str, Decimal]) -> list[dict[str, str]]:
    narrative = f"Wage accrual {month}"
    lines = [{"account": WAGES_ACCOUNT, "cost_centre": centre, "debit": plain(amount), "credit": "",
              "narrative": narrative} for centre, amount in sorted(accrued.items()) if amount]
    total = sum(accrued.values(), Decimal(0))
    if total:
        lines.append({"account": ACCRUED_WAGES_ACCOUNT, "cost_centre": "", "debit": "", "credit": plain(total),
                      "narrative": narrative})
    return lines


def write_journal(path: str | Path, month: str, accrued: dict[str, Decimal]) -> int:
    lines = journal_lines(month, accrued)
    write_rows(path, FIELDS, lines)
    return len(lines)
