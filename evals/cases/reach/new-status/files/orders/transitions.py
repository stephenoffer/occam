from orders.status import OrderStatus as S

ALLOWED = {
    S.PENDING: {S.PAID, S.CANCELLED},
    S.PAID: {S.SHIPPED, S.REFUNDED, S.CANCELLED},
    S.SHIPPED: {S.REFUNDED},
    S.REFUNDED: set(),
    S.CANCELLED: set(),
}


def move(order, status):
    if status not in ALLOWED[order.status]:
        raise ValueError(f"an order can't go from {order.status.value} to {status.value}")
    order.status = status
