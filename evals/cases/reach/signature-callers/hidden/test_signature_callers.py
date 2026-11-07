import importlib
import sys

import pytest


@pytest.fixture
def load(ws):
    """Import modules from the finished workspace, fresh for each test."""
    tops = {path.stem for path in ws.iterdir() if (path / "__init__.py").exists() or path.suffix == ".py"} - {"conftest", "tests"}
    for key in [key for key in sys.modules if key.split(".")[0] in tops]:
        del sys.modules[key]
    sys.path.insert(0, str(ws))
    yield importlib.import_module
    sys.path.remove(str(ws))


import importlib.util


def test_format_price_follows_the_table(load):
    money = load("shopfront.pricing.money")
    assert [money.format_price(1250, c) for c in ("USD", "EUR", "GBP", "JPY")] == ["$12.50", "\u20ac12.50", "\u00a312.50", "\u00a51250"]
    assert money.format_price(5, "EUR") == "\u20ac0.05"


def test_an_unknown_currency_is_refused(load):
    with pytest.raises(ValueError):
        load("shopfront.pricing.money").format_price(100, "XXX")


def test_the_currency_is_required(load):
    with pytest.raises(TypeError):
        load("shopfront.pricing.money").format_price(100)


def test_checkout_lines(load):
    assert load("shopfront.checkout.summary").order_line({"name": "Mug", "cents": 1250, "currency": "EUR"}) == "Mug: \u20ac12.50"


def test_daily_report(load):
    assert load("shopfront.reports.daily").revenue_row("2026-01-02", 1250, "JPY") == "2026-01-02\t\u00a51250"


def test_admin_export(load):
    rows = load("shopfront.admin.export").export_rows([{"id": 7, "customer": "Ana", "total_cents": 990, "currency": "GBP"}])
    assert rows == [["7", "Ana", "\u00a39.90"]]


def test_product_badge(load):
    assert load("shopfront.display").render_badge({"name": "Mug", "cents": 1250, "currency": "JPY"}) == "Mug - \u00a51250"


def test_invoice_backfill_script(ws):
    spec = importlib.util.spec_from_file_location("backfill_invoices", ws / "scripts" / "backfill_invoices.py")
    script = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ws))
    try:
        spec.loader.exec_module(script)
        assert script.invoice_text({"id": 3, "total_cents": 1250, "currency": "EUR"}) == "Invoice 3: \u20ac12.50"
    finally:
        sys.path.remove(str(ws))
