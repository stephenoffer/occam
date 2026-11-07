from decimal import Decimal

import pytest

from costing.oncosts import ONCOST_COMPONENTS, oncost_rate


def test_full_rate_is_the_sum_of_the_components():
    assert oncost_rate() == sum(ONCOST_COMPONENTS.values())
    assert oncost_rate() == Decimal("0.2937")


def test_holiday_can_be_left_out():
    assert oncost_rate(exclude=("holiday_accrual",)) == Decimal("0.173")


def test_unknown_components_are_an_error():
    with pytest.raises(KeyError):
        oncost_rate(exclude=("holiday",))
