from decimal import Decimal

import pytest

from timesheets.rounding import to_quarter_hours


@pytest.mark.parametrize("minutes, hours", [
    (0, "0"), (7, "0"), (8, "0.25"), (480, "8"), (487, "8"), (488, "8.25"), (370, "6.25"), (119, "2"),
])
def test_rounds_to_the_nearest_quarter_hour(minutes, hours):
    assert to_quarter_hours(minutes) == Decimal(hours)


def test_negative_time_is_an_error():
    with pytest.raises(ValueError):
        to_quarter_hours(-1)
