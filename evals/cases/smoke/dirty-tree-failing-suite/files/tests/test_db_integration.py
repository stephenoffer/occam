import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("ORDERS_TEST_DSN"), reason="needs ORDERS_TEST_DSN")


def test_order_round_trip():
    raise AssertionError("runs only against a real database")


def test_coupon_persisted():
    raise AssertionError("runs only against a real database")
