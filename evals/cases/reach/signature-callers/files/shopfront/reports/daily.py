from shopfront.pricing import money as m


def revenue_row(day, cents, currency):
    """A tab-separated row of the daily revenue report."""
    return f"{day}\t{m.format_price(cents)}"
