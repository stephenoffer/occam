from datetime import date
from decimal import Decimal

import pytest

from tidewater.core.errors import RateUnavailable
from tidewater.core.fx import contract_rate, currencies, is_known_currency, spot_rate


def test_spot_rate_from_usd():
    assert spot_rate("USD", "EUR", date(2026, 10, 20)) == Decimal("0.900000")


def test_spot_rate_cross():
    assert spot_rate("EUR", "GBP", date(2026, 10, 20)) == Decimal("0.933333")


def test_spot_rate_same_currency():
    assert spot_rate("JPY", "JPY", date(2026, 10, 20)) == Decimal("1.000000")


def test_spot_rate_unknown_currency():
    with pytest.raises(RateUnavailable):
        spot_rate("USD", "XTS", date(2026, 10, 20))


def test_spot_rate_on_an_earlier_date():
    assert spot_rate("USD", "EUR", date(2026, 5, 2)) == Decimal("0.950000")


def test_spot_rate_before_anything_was_published():
    with pytest.raises(RateUnavailable):
        spot_rate("USD", "EUR", date(2025, 12, 31))


def test_contract_rate():
    assert contract_rate("USD", "JPY") == Decimal("148.000000")


def test_contract_rate_cross():
    assert contract_rate("GBP", "EUR") == Decimal("1.125000")


def test_contract_rate_unknown_currency():
    with pytest.raises(RateUnavailable):
        contract_rate("USD", "XTS")


def test_currencies_start_with_the_pivot():
    assert currencies()[0] == "USD"


def test_known_currency():
    assert is_known_currency("SGD")
    assert not is_known_currency("XTS")
