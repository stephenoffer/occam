from orders.status import OrderStatus

LABELS = {
    OrderStatus.PENDING: "Pending",
    OrderStatus.PAID: "Paid",
    OrderStatus.SHIPPED: "Shipped",
    OrderStatus.REFUNDED: "Refunded",
    OrderStatus.CANCELLED: "Cancelled",
}


def label(status):
    """The dashboard's name for a status."""
    return LABELS[status]
