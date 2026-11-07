from decimal import Decimal

import pytest

from common.csvio import CsvError
from crew_factories import RATES_HEADER, write_csv
from payroll.rates import OVERTIME_MULTIPLIER, load_rates


def test_loads_rates(tmp_path):
    path = write_csv(tmp_path / "r.csv", RATES_HEADER, [["W1", "Ann Bell", "skilled", "20.00"]])
    rate = load_rates(path)["W1"]
    assert rate.base_hourly == Decimal("20.00")
    assert rate.overtime_hourly == Decimal("20.00") * OVERTIME_MULTIPLIER


@pytest.mark.parametrize("row, message", [
    (["W1", "Ann", "boss", "20"], "unknown grade"),
    (["W1", "Ann", "skilled", "0"], "positive"),
    (["W1", "Ann", "skilled", "lots"], "not an amount"),
])
def test_rejects_bad_rows(tmp_path, row, message):
    path = write_csv(tmp_path / "r.csv", RATES_HEADER, [row])
    with pytest.raises(CsvError, match=message):
        load_rates(path)


def test_rejects_duplicates(tmp_path):
    path = write_csv(tmp_path / "r.csv", RATES_HEADER, [["W1", "A", "skilled", "20"], ["W1", "A", "skilled", "21"]])
    with pytest.raises(CsvError, match="twice"):
        load_rates(path)
