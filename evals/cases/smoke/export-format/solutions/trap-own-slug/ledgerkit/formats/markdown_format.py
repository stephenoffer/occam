from ..money import round_invoice_total
import re
import unicodedata


def to_url_token(text):
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def _cell(value):
    return str(value).replace("|", "\\|")


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
