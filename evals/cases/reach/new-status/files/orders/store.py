import sqlite3
from dataclasses import dataclass

from orders.status import OrderStatus


@dataclass
class Order:
    id: int
    total_cents: int
    status: OrderStatus = OrderStatus.PAID
    refunded_cents: int = 0


def save(path, order):
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?)", (order.id, order.total_cents, order.refunded_cents, order.status.value))


def load(path, order_id):
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT id, total_cents, refunded_cents, status FROM orders WHERE id = ?", (order_id,)).fetchone()
    return Order(id=row[0], total_cents=row[1], refunded_cents=row[2], status=OrderStatus(row[3]))
