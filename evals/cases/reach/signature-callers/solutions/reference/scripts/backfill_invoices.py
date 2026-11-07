"""Re-render invoice text for invoices stored before the template change. Run from the repository root."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shopfront.pricing.money import format_price  # noqa: E402


def invoice_text(invoice):
    return f"Invoice {invoice['id']}: {format_price(invoice['total_cents'], invoice['currency'])}"


if __name__ == "__main__":
    for invoice in json.load(open(sys.argv[1])):
        print(invoice_text(invoice))
