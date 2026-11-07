from orders.status import OrderStatus

CODES = {
    OrderStatus.PENDING: "pending",
    OrderStatus.PAID: "paid",
    OrderStatus.SHIPPED: "shipped",
    OrderStatus.PARTIALLY_REFUNDED: "partially_refunded",
    OrderStatus.REFUNDED: "refunded",
    OrderStatus.CANCELLED: "cancelled",
}


def to_api(order):
    return {"id": order.id, "status": CODES[order.status], "total_cents": order.total_cents, "refunded_cents": order.refunded_cents}
