"""Line discounts on the tills, checked at every place that reads a day's sales.

Everything goes through the command lines the stores and finance use: `python -m till` to ring,
cash up and close the day, and `python -m backoffice takings` on what the close produced.
"""

import json
from pathlib import Path

import pytest

DAY = "2026-11-16"
FLOAT = 10000

# Three sales on one day. Gross, discount and net per line, in pence:
#   A  PNT-1L-WHT x2  2598 - 40 STAFF = 2558;  PLB-PTFE x1 99            cash 3000, change 343
#   B  GDN-HOSE-15M x1  1999 - 500 DAMAGED = 1499                         card 1499
#   C  TLS-HAM-16OZ x1  1499 - 150 PROMO = 1349;  FIX-NAIL-50 x2 1050 - 100 PROMO = 950
#                                                                         card 1000, cash 1500, change 201
BASKETS = [
    {"at": f"{DAY}T09:12:00",
     "lines": [{"sku": "PNT-1L-WHT", "qty": 2, "discount": {"pence": 40, "reason": "STAFF"}}, {"sku": "PLB-PTFE", "qty": 1}],
     "tenders": [{"type": "cash", "pence": 3000}]},
    {"at": f"{DAY}T11:30:00",
     "lines": [{"sku": "GDN-HOSE-15M", "qty": 1, "discount": {"pence": 500, "reason": "DAMAGED"}}],
     "tenders": [{"type": "card", "pence": 1499}]},
    {"at": f"{DAY}T15:05:00",
     "lines": [{"sku": "TLS-HAM-16OZ", "qty": 1, "discount": {"pence": 150, "reason": "PROMO"}},
               {"sku": "FIX-NAIL-50", "qty": 2, "discount": {"pence": 100, "reason": "PROMO"}}],
     "tenders": [{"type": "card", "pence": 1000}, {"type": "cash", "pence": 1500}]},
]
NET_SALES = 2657 + 1499 + 2299
NET_DEPARTMENTS = {"PNT": 2558, "PLB": 99, "GDN": 1499, "TLS": 1349, "FIX": 950}
DISCOUNTS = {"STAFF": "0.40", "DAMAGED": "5.00", "PROMO": "2.50"}
CASH_IN, CHANGE = 4500, 343 + 201


def fmt(pence: int) -> str:
    return f"{pence // 100}.{pence % 100:02d}"


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / "till"
    directory.mkdir()
    (directory / "till.ini").write_text(
        f"[till]\nstore = BRH04\nstore_name = Brindle Hardware Ripon\nnumber = 2\nfloat_pence = {FLOAT}\n", encoding="utf-8")
    return directory


def run_till(py, data_dir, *args):
    return py("-m", "till", "--data", str(data_dir), *args)


def ring_all(py, data_dir, tmp_path, baskets=BASKETS):
    receipts = []
    for number, basket in enumerate(baskets, start=1):
        path = tmp_path / f"basket-{number}.json"
        path.write_text(json.dumps(basket), encoding="utf-8")
        done = run_till(py, data_dir, "ring", str(path))
        assert done.returncode == 0, f"ringing basket {number} failed:\n{done.stdout}\n{done.stderr}"
        receipts.append(done.stdout)
    return receipts


def ends_with_amount(line: str, amount: str) -> bool:
    return line.rstrip().endswith(amount)


def test_receipt_shows_discount_and_charges_net(py, data, tmp_path):
    basket = {"at": f"{DAY}T10:00:00",
              "lines": [{"sku": "PNT-1L-WHT", "qty": 2, "discount": {"pence": 40, "reason": "STAFF"}},
                        {"sku": "TLS-TAPE-5M", "qty": 1}],
              "tenders": [{"type": "cash", "pence": 4000}]}
    [receipt] = ring_all(py, data, tmp_path, [basket])
    lines = receipt.splitlines()
    total = [line for line in lines if line.strip().upper().startswith("TOTAL")]
    change = [line for line in lines if line.strip().upper().startswith("CHANGE")]
    assert total and ends_with_amount(total[-1], "33.57"), f"the customer pays 25.58 + 7.99 = 33.57:\n{receipt}"
    assert change and ends_with_amount(change[-1], "6.43"), f"change from 40.00 is 6.43:\n{receipt}"
    item = next(i for i, line in enumerate(lines) if "Emulsion 1L Brilliant White" in line)
    total_at = lines.index(total[-1])
    assert any("0.40" in line for line in lines[item + 1:total_at]), f"the 0.40 discount isn't shown under its line:\n{receipt}"


def test_cashup_reports_net_sales_and_discounts(py, data, tmp_path):
    ring_all(py, data, tmp_path)
    expected_cash = FLOAT + CASH_IN - CHANGE
    done = run_till(py, data, "cashup", "--date", DAY, "--counted-cash", fmt(expected_cash), "--json")
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["sales_total_pence"] == NET_SALES
    assert report["expected_cash_pence"] == expected_cash
    assert report["variance_pence"] == 0

    done = run_till(py, data, "cashup", "--date", DAY, "--counted-cash", fmt(expected_cash))
    assert done.returncode == 0, done.stderr
    text = done.stdout
    for reason, amount in DISCOUNTS.items():
        assert any(reason in line.upper() and amount in line for line in text.splitlines()), \
            f"no line shows {reason} discounts of {amount}:\n{text}"
    assert fmt(NET_SALES) in text
    assert "WARNING" not in text, text


def test_head_office_takings_are_net_of_discounts(py, data, tmp_path):
    ring_all(py, data, tmp_path)
    done = run_till(py, data, "close", "--date", DAY)
    assert done.returncode == 0, done.stderr
    done = py("-m", "backoffice", "takings", "--inbox", str(data / "outbox"), "--date", DAY, "--json")
    assert done.returncode == 0, done.stderr
    store = json.loads(done.stdout)["stores"]["BRH04"]
    assert store["quarantined"] == [], store["quarantined"]
    assert store["sales_count"] == 3
    assert store["departments"] == NET_DEPARTMENTS
    assert store["sales_pence"] == NET_SALES
    assert store["banked_cash_pence"] == CASH_IN - CHANGE
    assert store["mismatches"] == [], "sales with discounts are flagged as not matching what was paid"


# Written exactly as the tills wrote them before this change.
OLD_RECORDS = [
    {"v": 1, "store": "BRH01", "till": 1, "sale": "BRH01-1-261026-0001", "at": "2026-10-26T09:41:00",
     "lines": [{"sku": "PNT-1L-WHT", "dept": "PNT", "qty": 2, "unit": 1299}, {"sku": "PLB-PTFE", "dept": "PLB", "qty": 1, "unit": 99}],
     "tenders": [{"type": "cash", "pence": 3000}], "change": 303},
    {"v": 1, "store": "BRH01", "till": 1, "sale": "BRH01-1-261026-0002", "at": "2026-10-26T13:02:00",
     "lines": [{"sku": "GDN-HOSE-15M", "dept": "GDN", "qty": 1, "unit": 1999}],
     "tenders": [{"type": "card", "pence": 1999}], "change": 0},
]


def write_records(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records), encoding="utf-8")


def test_existing_journals_and_tapes_still_read(py, tmp_path):
    data_dir = tmp_path / "till"
    write_records(data_dir / "journal" / "2026-10-26.jsonl", OLD_RECORDS)
    expected_cash = FLOAT + 3000 - 303
    done = run_till(py, data_dir, "cashup", "--date", "2026-10-26", "--counted-cash", fmt(expected_cash), "--json")
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["sales_total_pence"] == 2697 + 1999
    assert report["variance_pence"] == 0

    inbox = tmp_path / "inbox"
    write_records(inbox / "BRH01-2026-10-26.tape", OLD_RECORDS)
    done = py("-m", "backoffice", "takings", "--inbox", str(inbox), "--date", "2026-10-26", "--json")
    assert done.returncode == 0, done.stderr
    store = json.loads(done.stdout)["stores"]["BRH01"]
    assert store["quarantined"] == []
    assert store["departments"] == {"PNT": 2598, "PLB": 99, "GDN": 1999}
    assert store["sales_pence"] == 4696
    assert store["mismatches"] == []
