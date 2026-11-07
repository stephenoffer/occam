from shopfront.pricing.money import format_price as fmt


def export_rows(orders):
    """Rows for the admin CSV export: id, customer, total."""
    return [[str(order["id"]), order["customer"], fmt(order["total_cents"], order["currency"])] for order in orders]
