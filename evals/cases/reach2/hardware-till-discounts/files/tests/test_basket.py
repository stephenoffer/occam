import pytest

from helpers import CATALOG
from till.basket import BasketError, build_basket


def test_prices_lines_from_the_catalogue():
    basket = build_basket(CATALOG, [{"sku": "PNT-1L-WHT", "qty": 2}, {"sku": "fix-plug-red"}])
    assert [(l.sku, l.qty, l.unit_pence, l.total_pence) for l in basket.lines] == [
        ("PNT-1L-WHT", 2, 1299, 2598), ("FIX-PLUG-RED", 1, 249, 249)]
    assert basket.total_pence == 2847
    assert basket.item_count == 3


@pytest.mark.parametrize("entries, message", [
    ([], "empty"),
    ([{"qty": 1}], "needs a sku"),
    ([{"sku": "NOPE"}], "not in the catalogue"),
    ([{"sku": "PLB-PTFE", "qty": 0}], "quantity"),
    ([{"sku": "PLB-PTFE", "qty": 1.5}], "quantity"),
    ([{"sku": "PLB-PTFE", "qty": True}], "quantity"),
])
def test_rejects_bad_baskets(entries, message):
    with pytest.raises(BasketError, match=message):
        build_basket(CATALOG, entries)
