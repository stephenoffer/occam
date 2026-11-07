from orders.status import OrderStatus
from orders.transitions import move


def apply_refund(order, amount_cents):
    """Record a refund against an order. Returns the order."""
    if amount_cents <= 0 or amount_cents > order.total_cents - order.refunded_cents:
        raise ValueError("refund must be positive and no more than what's left")
    order.refunded_cents += amount_cents
    move(order, OrderStatus.REFUNDED)
    return order
