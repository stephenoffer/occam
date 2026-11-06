import csv
import io

from ..money import round_invoice_total


def export_csv(rows, *, summary_row=False):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["reference", "customer", "currency", "total"])
    for row in rows:
        writer.writerow([row["reference"], row["customer"], row["currency"], round_invoice_total(row["amount"])])
    if summary_row:
        writer.writerow(["TOTAL", "", "", round_invoice_total(sum(row["amount"] for row in rows))])
    return buffer.getvalue()
