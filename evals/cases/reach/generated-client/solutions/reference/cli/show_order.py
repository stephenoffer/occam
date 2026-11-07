from clients.orders_generated import OrderSummary


def _money(cents):
    return f"${cents // 100}.{cents % 100:02d}"


def render(payload):
    """One line for an order, from the orders API's JSON."""
    order = OrderSummary.from_json(payload)
    details = order.status if not order.discount_cents else f"{order.status}, {_money(order.discount_cents)} off"
    return f"Order {order.id}: {_money(order.total_cents)} ({details})"
