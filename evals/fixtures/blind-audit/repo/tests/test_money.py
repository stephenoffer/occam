from __future__ import annotations

from datetime import date

import pytest

from subledger.utils import dates, formatting, money


@pytest.mark.parametrize("amount, rate, expected", [(10000, "0.20", 2000), (150, "0.19", 29), (2906, "0.25", 727)])
def test_percent_of_rounds_half_up(amount, rate, expected):
    assert money.percent_of(amount, rate) == expected


@pytest.mark.parametrize("amount, currency, expected", [(123456, "gbp", "1,234.56 GBP"), (1000, "JPY", "1,000 JPY")])
def test_format_money(amount, currency, expected):
    assert money.format_money(amount, currency) == expected


def test_parse_and_display_dollars():
    assert money.parse_amount("12.50", "USD") == 1250
    assert formatting.display_amount(2900, "usd") == "29.00 USD"


@pytest.mark.parametrize(
    "start, months, expected",
    [(date(2026, 1, 15), 1, date(2026, 2, 15)), (date(2026, 1, 31), 1, date(2026, 2, 28)),
     (date(2024, 1, 31), 1, date(2024, 2, 29)), (date(2026, 11, 30), 3, date(2027, 2, 28))],
)
def test_add_months(start, months, expected):
    assert dates.add_months(start, months) == expected


def test_month_bounds_rejects_garbage():
    with pytest.raises(ValueError):
        dates.month_bounds("not-a-month")
