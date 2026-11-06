import json
from decimal import Decimal


def load_ledger(path):
    with open(path) as handle:
        entries = json.load(handle, parse_float=Decimal)
    return [{**entry, "amount": Decimal(str(entry["amount"]))} for entry in entries]


def filter_rows(rows, currency=None):
    if currency is None:
        return rows
    return [row for row in rows if row["currency"] == currency]
