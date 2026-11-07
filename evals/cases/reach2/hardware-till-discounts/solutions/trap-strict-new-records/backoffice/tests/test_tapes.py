from datetime import date

import pytest

from backoffice.tapes import read_tape
from tape_helpers import FIXTURES, record, write_tape


def test_reads_a_real_tape():
    tape = read_tape(FIXTURES / "BRH02-2026-10-05.tape")
    assert (tape.store, tape.day) == ("BRH02", date(2026, 10, 5))
    assert [s.sale for s in tape.sales] == ["BRH02-1-261005-0001", "BRH02-2-261005-0001", "BRH02-1-261005-0002"]
    assert tape.sales[0].line_total == 5799 and tape.sales[0].paid == 5799
    assert tape.sales[2].tenders == {"card": 1000, "cash": 500}
    assert tape.quarantined == []


def test_blank_lines_are_skipped():
    tape = read_tape(FIXTURES / "BRH05-2026-10-05.tape")
    assert len(tape.sales) == 2 and tape.quarantined == []


@pytest.mark.parametrize("bad, reason", [
    (record(v=7), "unknown version"),
    ({k: v for k, v in record().items() if k != "change"}, "missing change"),
    (record(lines=[]), "at least one line"),
    (record(lines=[{"sku": "X", "dept": "FIX", "qty": 0, "unit": 10}]), "qty"),
    (record(tenders=[{"type": "voucher", "pence": 99}]), "unknown tender"),
    (record(store="BRH09"), "store BRH09"),
    (record(at="2026-11-08T23:59:59"), "dated"),
    ("{not json", "Expecting"),
])
def test_bad_records_are_quarantined_not_fatal(tmp_path, bad, reason):
    path = write_tape(tmp_path, "BRH01-2026-11-09.tape", [record(), bad, record(sale="BRH01-1-261109-0003")])
    tape = read_tape(path)
    assert len(tape.sales) == 2
    [q] = tape.quarantined
    assert q.line_no == 2 and reason in q.reason


def test_unknown_fields_are_ignored(tmp_path):
    path = write_tape(tmp_path, "BRH01-2026-11-09.tape", [record(loyalty_card="1234")])
    assert len(read_tape(path).sales) == 1


def test_badly_named_file(tmp_path):
    path = write_tape(tmp_path, "brh01_20261109.txt", [record()])
    with pytest.raises(ValueError, match="not named like a tape"):
        read_tape(path)


def test_version_2_line_discounts(tmp_path):
    line = {"sku": "PNT-1L-WHT", "dept": "PNT", "qty": 2, "unit": 1299, "discount": {"pence": 40, "reason": "STAFF"}}
    path = write_tape(tmp_path, "BRH01-2026-11-09.tape",
                      [record(v=2, lines=[line], tenders=[{"type": "cash", "pence": 3000}], change=442)])
    [sale] = read_tape(path).sales
    assert sale.lines[0].amount == 2558 and sale.lines[0].discount_reason == "STAFF"
    assert sale.line_total == sale.paid


@pytest.mark.parametrize("version, discount, reason", [
    (2, {"pence": 40, "reason": "FRIEND"}, "discount reason"),
    (2, {"pence": 5000, "reason": "PROMO"}, "more than the line"),
])
def test_bad_discounts_are_quarantined(tmp_path, version, discount, reason):
    line = {"sku": "PNT-1L-WHT", "dept": "PNT", "qty": 2, "unit": 1299, "discount": discount}
    tape = read_tape(write_tape(tmp_path, "BRH01-2026-11-09.tape", [record(v=version, lines=[line])]))
    assert tape.sales == [] and reason in tape.quarantined[0].reason
