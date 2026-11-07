from orders.status import OrderStatus

SUBJECTS = {
    OrderStatus.PENDING: "We've got your order",
    OrderStatus.PAID: "Payment received",
    OrderStatus.SHIPPED: "Your order is on its way",
    OrderStatus.REFUNDED: "Your refund is on its way",
    OrderStatus.CANCELLED: "Your order was cancelled",
}


def subject_for(status):
    return SUBJECTS[status]
