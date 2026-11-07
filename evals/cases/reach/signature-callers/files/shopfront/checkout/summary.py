from shopfront.pricing.money import format_price


def order_line(item):
    """One line of the checkout summary: an item dict with name, cents and currency."""
    return f"{item['name']}: {format_price(item['cents'])}"
