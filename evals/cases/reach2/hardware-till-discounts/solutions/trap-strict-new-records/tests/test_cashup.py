from datetime import date

from helpers import CATALOG, basket, write_settings
from till.cashup import as_json, cash_up, render
from till.ring import ring

DAY = date(2026, 11, 9)


def ring_day(data_dir):
    write_settings(data_dir, float_pence=10000)
    ring(data_dir, basket("2026-11-09T09:00:00", [{"sku": "PNT-1L-WHT", "qty": 2}, {"sku": "PLB-PTFE"}],
                          [{"type": "cash", "pence": 3000}]), CATALOG)
    ring(data_dir, basket("2026-11-09T10:00:00", [{"sku": "GDN-HOSE-15M"}], [{"type": "card", "pence": 1999}]), CATALOG)
    ring(data_dir, basket("2026-11-09T11:00:00", [{"sku": "TLS-HAM-16OZ"}, {"sku": "FIX-NAIL-50"}],
                          [{"type": "card", "pence": 1000}, {"type": "cash", "pence": 1100}]), CATALOG)


def test_totals(tmp_path):
    ring_day(tmp_path)
    result = cash_up(tmp_path, DAY)
    assert result.sales_count == 3
    assert result.sales_total_pence == 2697 + 1999 + 2024
    assert dict(result.departments) == {"PNT": 2598, "PLB": 99, "GDN": 1999, "TLS": 1499, "FIX": 525}
    assert dict(result.tenders) == {"cash": 4100, "card": 2999}
    assert result.change_pence == 303 + 76
    assert result.expected_cash_pence == 10000 + 4100 - 379
    assert result.paid_pence == result.sales_total_pence


def test_variance(tmp_path):
    ring_day(tmp_path)
    assert cash_up(tmp_path, DAY, counted_cash_pence=13721).variance_pence == 0
    assert cash_up(tmp_path, DAY, counted_cash_pence=13700).variance_pence == -21
    assert cash_up(tmp_path, DAY).variance_pence is None


def test_json_and_text(tmp_path):
    ring_day(tmp_path)
    result = cash_up(tmp_path, DAY, counted_cash_pence=13721)
    data = as_json(result)
    assert data["sales_total_pence"] == 6720 and data["variance_pence"] == 0
    assert data["departments"]["GDN"] == 1999
    text = render(result)
    assert "Sales (3)" in text and "67.20" in text
    assert "Expected cash in drawer" in text and "137.21" in text
    assert "WARNING" not in text


def test_empty_day(tmp_path):
    write_settings(tmp_path)
    result = cash_up(tmp_path, DAY, counted_cash_pence=10000)
    assert result.sales_count == 0 and result.variance_pence == 0


def test_discounts_are_net_and_listed_by_reason(tmp_path):
    write_settings(tmp_path, float_pence=10000)
    ring(tmp_path, basket("2026-11-09T09:00:00",
                          [{"sku": "PNT-1L-WHT", "qty": 2, "discount": {"pence": 40, "reason": "STAFF"}}],
                          [{"type": "cash", "pence": 3000}]), CATALOG)
    ring(tmp_path, basket("2026-11-09T10:00:00",
                          [{"sku": "GDN-HOSE-15M", "discount": {"pence": 500, "reason": "DAMAGED"}},
                           {"sku": "TLS-TAPE-5M", "discount": {"pence": 80, "reason": "PROMO"}}],
                          [{"type": "card", "pence": 2218}]), CATALOG)
    result = cash_up(tmp_path, DAY, counted_cash_pence=10000 + 2558)
    assert result.sales_total_pence == 2558 + 2218
    assert dict(result.departments) == {"PNT": 2558, "GDN": 1499, "TLS": 719}
    assert dict(result.discounts) == {"STAFF": 40, "DAMAGED": 500, "PROMO": 80}
    assert result.variance_pence == 0
    assert as_json(result)["discounts"] == {"DAMAGED": 500, "PROMO": 80, "STAFF": 40}
    text = render(result)
    assert "Discounts given" in text and "6.20" in text
    assert any("STAFF" in l and l.endswith("0.40") for l in text.splitlines())
    assert "WARNING" not in text
