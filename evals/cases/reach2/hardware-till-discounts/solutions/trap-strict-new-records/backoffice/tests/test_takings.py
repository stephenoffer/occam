from datetime import date

from backoffice.takings import as_json, takings_for_day
from tape_helpers import copy_fixtures, record, write_tape

DAY = date(2026, 10, 5)


def test_takings_per_store(tmp_path):
    takings = takings_for_day(copy_fixtures(tmp_path / "inbox"), DAY)
    assert sorted(takings) == ["BRH02", "BRH05"]
    brh02 = takings["BRH02"]
    assert brh02.sales_count == 3
    assert brh02.sales_pence == 5799 + 1147 + 1349
    assert dict(brh02.departments) == {"PNT": 5799, "FIX": 1147, "ELC": 1349}
    assert brh02.banked_cash_pence == 2500 - 1004
    assert brh02.tenders["card"] == 6799
    assert brh02.mismatches == [] and brh02.quarantined == []


def test_sale_that_doesnt_add_up_is_flagged(tmp_path):
    inbox = tmp_path / "inbox"
    write_tape(inbox, "BRH01-2026-10-05.tape", [
        record(sale="A", at="2026-10-05T09:00:00"),
        record(sale="B", at="2026-10-05T09:05:00", tenders=[{"type": "cash", "pence": 500}], change=300),
    ])
    takings = takings_for_day(inbox, DAY)["BRH01"]
    assert takings.mismatches == ["B"]
    assert takings.sales_count == 2


def test_duplicate_sale_is_flagged(tmp_path):
    inbox = tmp_path / "inbox"
    write_tape(inbox, "BRH01-2026-10-05.tape", [record(sale="A", at="2026-10-05T09:00:00"),
                                                record(sale="A", at="2026-10-05T09:00:00")])
    assert takings_for_day(inbox, DAY)["BRH01"].mismatches == ["A"]


def test_json_shape(tmp_path):
    data = as_json(takings_for_day(copy_fixtures(tmp_path / "inbox"), DAY))
    brh05 = data["stores"]["BRH05"]
    assert brh05 == {"sales_count": 2, "sales_pence": 4446, "departments": {"GDN": 2796, "TLS": 1650},
                     "tenders": {"card": 1650, "cash": 3000}, "discounts": {}, "change_pence": 204, "banked_cash_pence": 2796,
                     "mismatches": [], "quarantined": []}


def test_no_tapes_no_takings(tmp_path):
    assert takings_for_day(tmp_path, DAY) == {}


def test_discounted_sales_are_net_and_balance(tmp_path):
    inbox = tmp_path / "inbox"
    lines = [{"sku": "GDN-HOSE-15M", "dept": "GDN", "qty": 1, "unit": 1999, "discount": {"pence": 500, "reason": "DAMAGED"}},
             {"sku": "PLB-PTFE", "dept": "PLB", "qty": 1, "unit": 99}]
    write_tape(inbox, "BRH01-2026-10-05.tape", [
        record(sale="A", at="2026-10-05T09:00:00", lines=lines, tenders=[{"type": "card", "pence": 1598}]),
        record(sale="B", at="2026-10-05T09:30:00"),
    ])
    takings = takings_for_day(inbox, DAY)["BRH01"]
    assert dict(takings.departments) == {"GDN": 1499, "PLB": 198}
    assert takings.sales_pence == 1598 + 99
    assert dict(takings.discounts) == {"DAMAGED": 500}
    assert takings.mismatches == [] and takings.quarantined == []
