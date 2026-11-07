import json
from datetime import date, datetime

import pytest

from till import journal
from till.tender import Tender


def sale(number=1, at="2026-11-09T09:14:03"):
    return journal.SaleRecord(
        store="BRH01", till=1, sale=f"BRH01-1-261109-{number:04d}", at=datetime.fromisoformat(at),
        lines=(journal.RecordLine("PNT-1L-WHT", "PNT", 2, 1299), journal.RecordLine("PLB-PTFE", "PLB", 1, 99)),
        tenders=(Tender("cash", 3000),), change_pence=303)


def test_append_and_read_back(tmp_path):
    path = journal.append(tmp_path, sale())
    assert path == tmp_path / "journal" / "2026-11-09.jsonl"
    [back] = journal.read_day(tmp_path, date(2026, 11, 9))
    assert back == sale()
    assert back.total_pence == 2697


def test_record_shape(tmp_path):
    journal.append(tmp_path, sale())
    record = json.loads((tmp_path / "journal" / "2026-11-09.jsonl").read_text())
    assert record == {"v": 2, "store": "BRH01", "till": 1, "sale": "BRH01-1-261109-0001", "at": "2026-11-09T09:14:03",
                      "lines": [{"sku": "PNT-1L-WHT", "dept": "PNT", "qty": 2, "unit": 1299},
                                {"sku": "PLB-PTFE", "dept": "PLB", "qty": 1, "unit": 99}],
                      "tenders": [{"type": "cash", "pence": 3000}], "change": 303}


def test_sale_ids_count_up_per_day(tmp_path):
    assert journal.next_sale_id(tmp_path, "BRH01", 1, date(2026, 11, 9)) == "BRH01-1-261109-0001"
    journal.append(tmp_path, sale())
    assert journal.next_sale_id(tmp_path, "BRH01", 1, date(2026, 11, 9)) == "BRH01-1-261109-0002"
    assert journal.next_sale_id(tmp_path, "BRH01", 1, date(2026, 11, 10)) == "BRH01-1-261110-0001"


def test_missing_day_is_empty(tmp_path):
    assert journal.read_day(tmp_path, date(2026, 1, 1)) == []


def test_unreadable_line_names_the_place(tmp_path):
    journal.append(tmp_path, sale())
    with open(tmp_path / "journal" / "2026-11-09.jsonl", "a") as handle:
        handle.write('{"v": 99}\n')
    with pytest.raises(journal.JournalError, match="line 2"):
        journal.read_day(tmp_path, date(2026, 11, 9))


def test_discounts_round_trip(tmp_path):
    discounted = journal.SaleRecord(
        store="BRH01", till=1, sale="BRH01-1-261109-0001", at=datetime(2026, 11, 9, 9, 0),
        lines=(journal.RecordLine("PNT-1L-WHT", "PNT", 2, 1299, 40, "STAFF"),),
        tenders=(Tender("cash", 3000),), change_pence=442)
    journal.append(tmp_path, discounted)
    record = json.loads((tmp_path / "journal" / "2026-11-09.jsonl").read_text())
    assert record["lines"][0]["discount"] == {"pence": 40, "reason": "STAFF"}
    [back] = journal.read_day(tmp_path, date(2026, 11, 9))
    assert back == discounted and back.total_pence == 2558

