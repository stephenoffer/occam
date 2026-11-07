from shopfront.pricing.money import format_price


def test_dollars():
    assert format_price(1250) == "$12.50"


def test_small_amounts_keep_two_digits():
    assert format_price(5) == "$0.05"
