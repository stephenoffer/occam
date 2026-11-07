from datetime import datetime

from helpers import CATALOG
from till.basket import build_basket
from till.receipt import WIDTH, render_receipt
from till.tender import Tender


def render(entries, tenders, change):
    basket = build_basket(CATALOG, entries)
    return render_receipt(store_name="Brindle Test", till=1, sale="BRH01-1-261109-0001",
                          at=datetime(2026, 11, 9, 9, 14, 3), basket=basket, tenders=tenders, change_pence=change)


def test_receipt_layout():
    text = render([{"sku": "PNT-1L-WHT", "qty": 2}, {"sku": "PNT-BRUSH-2IN"}], [Tender("cash", 3000)], 3)
    lines = text.splitlines()
    assert lines[0] == "Brindle Test"
    assert "09/11/2026 09:14" in text
    assert "  2 @ 12.99" in lines
    assert any(l.startswith("Emulsion 1L Brilliant White") and l.endswith("25.98") for l in lines)
    assert any(l.startswith("TOTAL") and l.endswith("29.97") for l in lines)
    assert any(l.startswith("CASH") and l.endswith("30.00") for l in lines)
    assert any(l.startswith("CHANGE") and l.endswith("0.03") for l in lines)
    assert "Items: 3" in lines


def test_fits_the_printer():
    text = render([{"sku": "FIX-SCR-4X40", "qty": 120}], [Tender("cash", 80000)], 2120)
    assert max(len(line) for line in text.splitlines()) <= WIDTH
