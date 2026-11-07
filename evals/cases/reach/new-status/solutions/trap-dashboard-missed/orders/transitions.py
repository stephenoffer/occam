from orders.status import OrderStatus as S

ALLOWED = {
    S.PENDING: {S.PAID, S.CANCELLED},
    S.PAID: {S.SHIPPED, S.PARTIALLY_REFUNDED, S.REFUNDED, S.CANCELLED},
    S.SHIPPED: {S.PARTIALLY_REFUNDED, S.REFUNDED},
    S.PARTIALLY_REFUNDED: {S.PARTIALLY_REFUNDED, S.REFUNDED},
    S.REFUNDED: set(),
    S.CANCELLED: set(),
}


def move(order, status):
    if status not in ALLOWED[order.status]:
        raise ValueError(f"an order can't go from {order.status.value} to {status.value}")
    order.status = status
