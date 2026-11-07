from datetime import date

import pytest

from helpers import CATALOG, basket, write_settings
from stock.deplete import deplete_day
from stock.levels import load_levels, receive_delivery, save_levels
from till.ring import ring


def test_deplete_takes_quantities_off(tmp_path):
    write_settings(tmp_path)
    save_levels(tmp_path, {"PNT-1L-WHT": 10, "PLB-PTFE": 1})
    ring(tmp_path, basket("2026-11-09T09:00:00", [{"sku": "PNT-1L-WHT", "qty": 3}, {"sku": "PLB-PTFE", "qty": 2}],
                          [{"type": "cash", "pence": 5000}]), CATALOG)
    assert deplete_day(tmp_path, date(2026, 11, 9)) == ["PLB-PTFE"]
    assert load_levels(tmp_path) == {"PNT-1L-WHT": 7, "PLB-PTFE": -1}


def test_a_day_is_only_taken_off_once(tmp_path):
    write_settings(tmp_path)
    deplete_day(tmp_path, date(2026, 11, 9))
    with pytest.raises(RuntimeError, match="already"):
        deplete_day(tmp_path, date(2026, 11, 9))


def test_deliveries(tmp_path):
    assert receive_delivery(tmp_path, {"GDN-HOSE-15M": 6}) == {"GDN-HOSE-15M": 6}
    with pytest.raises(ValueError):
        receive_delivery(tmp_path, {"GDN-HOSE-15M": 0})
