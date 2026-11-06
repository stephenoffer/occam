import json
from decimal import Decimal

from freightquote.fuel import read_fuel_rate


def test_published_index_uses_the_latest_week(fuel_index):
    assert read_fuel_rate(fuel_index) == Decimal("0.121")


def test_latest_week_is_by_date_not_file_order(tmp_path):
    path = tmp_path / "fuel.json"
    weeks = [
        {"published": "2026-11-02", "rate": "0.2"},
        {"published": "2026-10-26", "rate": "0.1"},
    ]
    path.write_text(json.dumps({"weeks": weeks}))
    assert read_fuel_rate(path) == Decimal("0.2")


def test_index_not_published_yet_means_no_fuel_line_amount(tmp_path):
    assert read_fuel_rate(tmp_path / "not-published.json") == Decimal("0")
