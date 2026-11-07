from orders.refunds import apply_refund
from orders.store import Order


def test_a_full_refund():
    assert apply_refund(Order(id=1, total_cents=500), 500).status.value == "REFUNDED"
