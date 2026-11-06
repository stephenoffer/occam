import json
import shutil
from pathlib import Path

import pytest

from toolhire.desk import main

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "shop.json"


@pytest.fixture
def shop(tmp_path):
    path = tmp_path / "shop.json"
    shutil.copy(EXAMPLE, path)
    return str(path)


def run(capsys, *args):
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_quote_prints_json(shop, capsys):
    code, out, _ = run(capsys, "quote", shop, "--category", "DRILL", "--start", "2026-03-02", "--end", "2026-03-09")
    assert code == 0
    assert json.loads(out)["hire"] == "72.00"


def test_book_and_cancel(shop, capsys):
    code, out, _ = run(capsys, "book", shop, "C-1", "--category", "SAW", "--start", "2026-04-06", "--end", "2026-04-08")
    assert (code, out.strip()) == (0, "B-2")
    assert run(capsys, "cancel-booking", shop, "B-2")[0] == 0
    assert run(capsys, "cancel-booking", shop, "B-2")[0] == 1


def test_checkout_extend_and_return(shop, capsys):
    code, out, _ = run(capsys, "checkout", shop, "C-1", "DR-101", "--start", "2026-03-02", "--due", "2026-03-06")
    assert (code, out.strip()) == (0, "R-3")
    code, out, _ = run(capsys, "extend", shop, "R-3", "--to", "2026-03-11", "--by", "Sam")
    assert code == 0 and "now due 2026-03-11" in out
    code, out, _ = run(capsys, "return", shop, "R-3", "--on", "2026-03-11")
    assert code == 0 and json.loads(out)["late_fee"] == "0.00"


def test_return_dry_run_changes_nothing(shop, capsys):
    before = Path(shop).read_text()
    code, out, _ = run(capsys, "return", shop, "R-1", "--on", "2026-03-10", "--dry-run")
    assert code == 0
    assert json.loads(out)["late_fee"] == "54.00"
    assert Path(shop).read_text() == before


def test_errors_are_reported_not_raised(shop, capsys):
    code, _, err = run(capsys, "return", shop, "R-99", "--on", "2026-03-10")
    assert code == 1
    assert "no rental R-99" in err


def test_dispute_blocks_a_return(shop, capsys):
    assert run(capsys, "dispute", shop, "R-1", "--reason", "faulty")[0] == 0
    code, _, err = run(capsys, "return", shop, "R-1", "--on", "2026-03-10")
    assert code == 1 and "in dispute" in err
    assert run(capsys, "resolve-dispute", shop, "R-1")[0] == 0


def test_reminders_table_and_letters(shop, capsys):
    code, out, _ = run(capsys, "reminders", shop, "--as-of", "2026-03-14", "--format", "json")
    assert code == 0
    assert {row["rental"]: row["stage"] for row in json.loads(out)} == {"R-1": "firm", "R-2": "firm"}
    code, out, _ = run(capsys, "reminders", shop, "--as-of", "2026-03-14", "--letters")
    assert code == 0 and "Subject: firm reminder for R-1" in out


def test_reports_take_format(shop, capsys):
    code, out, _ = run(capsys, "deposits", shop, "--format", "csv")
    assert code == 0
    assert out.splitlines() == ["rental,customer,asset,deposit_held", "R-1,C-1,DR-100,50.00", "R-2,C-2,MX-200,40.00"]
    code, out, _ = run(capsys, "utilization", shop, "--as-of", "2026-03-10", "--format", "json")
    assert code == 0 and {row["category"] for row in json.loads(out)} == {"DRILL", "MIXER", "SAW"}
    for name in ("customers", "fleet"):
        assert run(capsys, name, shop, "--format", "json")[0] == 0
    assert run(capsys, "service-due", shop, "--as-of", "2026-03-10")[0] == 0
    assert run(capsys, "availability", shop, "--category", "SAW", "--start", "2026-03-23", "--end", "2026-03-25")[0] == 0


def test_work_order_invoice_credit_flow(shop, capsys):
    assert run(capsys, "work-order", shop, "SW-300", "--on", "2026-03-02", "--reason", "blade")[1].strip() == "W-1"
    assert run(capsys, "close-work-order", shop, "W-1", "--on", "2026-03-03", "--cost", "20.00")[0] == 0
    assert run(capsys, "return", shop, "R-1", "--on", "2026-03-06")[0] == 0
    code, out, _ = run(capsys, "invoice", shop, "R-1", "--on", "2026-03-06")
    assert code == 0 and out.startswith("INVOICE INV-1")
    code, out, _ = run(capsys, "revenue", shop, "--from", "2026-03-01", "--to", "2026-04-01", "--format", "csv")
    assert out.splitlines()[1] == "DRILL,72.00"
    code, out, _ = run(capsys, "credit", shop, "INV-1", "--on", "2026-03-07", "--reason", "Goodwill")
    assert code == 0 and out.startswith("CREDIT NOTE INV-2")
