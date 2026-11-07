from decimal import Decimal

import pytest

from common.money import fmt, parse_money, pennies, plain


def test_pennies_round_half_up():
    assert pennies(Decimal("1.005")) == Decimal("1.01")
    assert pennies(Decimal("2.675")) == Decimal("2.68")
    assert pennies(Decimal("-1.005")) == Decimal("-1.01")


def test_parse_money_accepts_pounds_and_separators():
    assert parse_money("£1,234.50") == Decimal("1234.50")
    assert parse_money(" 18 ") == Decimal("18")


@pytest.mark.parametrize("text", ["", "abc", "NaN", "Infinity"])
def test_parse_money_rejects_junk(text):
    with pytest.raises(ValueError):
        parse_money(text)


def test_formats():
    assert fmt(Decimal("1234.5")) == "1,234.50"
    assert plain(Decimal("1234.5")) == "1234.50"
