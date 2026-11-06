import json

from ..money import round_invoice_total


def export_json(rows, *, summary_row=False):
    entries = [
        {
            "reference": row["reference"],
            "customer": row["customer"],
            "currency": row["currency"],
            "total": str(round_invoice_total(row["amount"])),
        }
        for row in rows
    ]
    if summary_row:
        entries.append({"reference": "TOTAL", "total": str(round_invoice_total(sum(row["amount"] for row in rows)))})
    return json.dumps(entries, indent=2) + "\n"
