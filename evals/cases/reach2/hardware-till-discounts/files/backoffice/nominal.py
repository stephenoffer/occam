"""Postings for the accounts package, one CSV row per nominal account per store per day.

Department sales post to the sales accounts below. Cash banked posts to the store's bank account,
card to the card clearing account that the acquirer's settlement later clears.
"""

from __future__ import annotations

import csv
import io

from backoffice.takings import StoreTakings

SALES_ACCOUNTS = {
    "PNT": "4010",
    "FIX": "4020",
    "TLS": "4030",
    "GDN": "4040",
    "ELC": "4050",
    "PLB": "4060",
}
UNALLOCATED_SALES = "4090"
BANK = "1200"
CARD_CLEARING = "1210"


def postings(takings: StoreTakings) -> list[tuple[str, str, str, int]]:
    """(account, store, reference, amount in pence). Credits are negative, as the accounts package expects."""
    day = takings.day.isoformat()
    rows = []
    for dept, pence in sorted(takings.departments.items()):
        rows.append((SALES_ACCOUNTS.get(dept, UNALLOCATED_SALES), takings.store, f"{day} {dept}", -pence))
    rows.append((BANK, takings.store, f"{day} cash", takings.banked_cash_pence))
    if takings.tenders["card"]:
        rows.append((CARD_CLEARING, takings.store, f"{day} card", takings.tenders["card"]))
    return rows


def to_csv(all_takings: list[StoreTakings]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["account", "store", "reference", "amount"])
    for takings in all_takings:
        for account, store, reference, pence in postings(takings):
            sign = "-" if pence < 0 else ""
            writer.writerow([account, store, reference, f"{sign}{abs(pence) // 100}.{abs(pence) % 100:02d}"])
    return out.getvalue()
