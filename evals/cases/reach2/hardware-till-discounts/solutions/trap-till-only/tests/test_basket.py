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


def test_discount_comes_off_the_line():
    basket = build_basket(CATALOG, [{"sku": "PNT-1L-WHT", "qty": 2, "discount": {"pence": 40, "reason": "STAFF"}},
                                    {"sku": "PLB-PTFE"}])
    line = basket.lines[0]
    assert (line.gross_pence, line.discount_pence, line.discount_reason, line.total_pence) == (2598, 40, "STAFF", 2558)
    assert basket.total_pence == 2558 + 99


@pytest.mark.parametrize("discount, message", [
    ({"pence": 40}, "reason"),
    ({"pence": 40, "reason": "FRIEND"}, "reason"),
    ({"pence": 0, "reason": "PROMO"}, "discount must be"),
    ({"pence": 2599, "reason": "PROMO"}, "discount must be"),
    ({"pence": 1.5, "reason": "PROMO"}, "discount must be"),
    ("40", "needs pence"),
])
def test_rejects_bad_discounts(discount, message):
    with pytest.raises(BasketError, match=message):
        build_basket(CATALOG, [{"sku": "PNT-1L-WHT", "qty": 2, "discount": discount}])
