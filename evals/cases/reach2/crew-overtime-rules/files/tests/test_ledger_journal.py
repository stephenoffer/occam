from decimal import Decimal

from ledger.journal import journal_lines


def test_one_debit_per_cost_centre_and_one_credit():
    lines = journal_lines("2026-11", {"CC-420": Decimal("100.50"), "CC-410": Decimal("20")})
    assert [(l["account"], l["cost_centre"], l["debit"], l["credit"]) for l in lines] == [
        ("5100", "CC-410", "20.00", ""), ("5100", "CC-420", "100.50", ""), ("2210", "", "", "120.50")]
    assert {l["narrative"] for l in lines} == {"Wage accrual 2026-11"}


def test_nothing_to_post():
    assert journal_lines("2026-11", {}) == []
