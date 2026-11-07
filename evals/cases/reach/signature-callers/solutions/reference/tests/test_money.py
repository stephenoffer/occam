import pytest

from shopfront.pricing.money import format_price


@pytest.mark.parametrize("amount, currency, shown", [(1250, "USD", "$12.50"), (1250, "JPY", "\u00a51250"), (5, "EUR", "\u20ac0.05")])
def test_formats(amount, currency, shown):
    assert format_price(amount, currency) == shown
