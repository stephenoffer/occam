from orders.tax import vat


def test_vat_simple():
    assert vat(100) == 21


def test_vat_rounding():
    assert vat(1.15, rate=0.1) in (0.11, 0.12)
