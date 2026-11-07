from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
