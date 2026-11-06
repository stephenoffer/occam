from datetime import date
from decimal import Decimal

import pytest

from tidewater.core import dates, ids, money, tabular, text, units


def test_round_cents_half_up():
    assert money.round_cents(Decimal("1.005")) == Decimal("1.01")


def test_percent_of():
    assert money.percent_of(Decimal("200"), Decimal("2.5")) == Decimal("5")


def test_add_months_clamps():
    assert dates.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_month_end():
    assert dates.month_end(date(2026, 2, 3)) == date(2026, 2, 28)


def test_following_weekday():
    assert dates.following_weekday(date(2026, 3, 6)) == date(2026, 3, 9)


def test_check_digit_round_trip():
    assert ids.is_valid(ids.with_check_digit("SHIP42"))


def test_pad_refuses_overflow():
    with pytest.raises(ValueError):
        text.pad("too long", 3)


def test_truncate():
    assert text.truncate("harbour", 4) == "har~"


def test_render_rows():
    assert tabular.render_rows(["a"], [["1"]]).splitlines()[-1] == "1"


def test_tonnes():
    assert units.tonnes_from_kg(Decimal("2500")) == Decimal("2.5")
