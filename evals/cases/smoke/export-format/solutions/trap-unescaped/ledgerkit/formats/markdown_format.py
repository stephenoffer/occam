from ..money import round_invoice_total
from ..text import to_url_token


def _cell(value):
    return str(value)


def export_markdown(rows, *, summary_row=False):
    lines = ["| Reference | Customer | Currency | Total |", "| --- | --- | --- | --- |"]
    for row in rows:
        cells = [to_url_token(row["reference"]), _cell(row["customer"]), _cell(row["currency"]),
                 round_invoice_total(row["amount"])]
        lines.append("| " + " | ".join(str(cell) for cell in cells) + " |")
    if summary_row:
        total = round_invoice_total(sum(row["amount"] for row in rows))
        lines.append(f"| TOTAL |  |  | {total} |")
    return "\n".join(lines) + "\n"
