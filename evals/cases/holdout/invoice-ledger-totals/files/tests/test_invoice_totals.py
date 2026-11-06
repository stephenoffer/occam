import csv
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def billing_totals():
    with open(ROOT / "data" / "billing_totals.csv", newline="") as handle:
        return {int(row["invoice_id"]): (row["currency"], row["total"]) for row in csv.DictReader(handle)}


@pytest.fixture(scope="module")
def report():
    connection = sqlite3.connect(":memory:")
    connection.executescript((ROOT / "sql" / "schema.sql").read_text())
    connection.executescript((ROOT / "data" / "sample_seed.sql").read_text())
    cursor = connection.execute((ROOT / "sql" / "invoice_totals.sql").read_text())
    columns = [column[0] for column in cursor.description]
    rows = cursor.fetchall()
    connection.close()
    return columns, rows


def test_output_columns(report):
    assert report[0] == ["invoice_id", "currency", "total"]


def test_rows_are_ordered_by_invoice(report):
    ids = [row[0] for row in report[1]]
    assert ids == sorted(ids) == sorted(billing_totals())


@pytest.mark.parametrize("invoice_id", sorted(billing_totals()))
def test_total_matches_billing(report, invoice_id):
    rows = {row[0]: row[1:] for row in report[1]}
    assert rows[invoice_id] == billing_totals()[invoice_id]
