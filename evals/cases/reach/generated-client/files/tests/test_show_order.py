from cli.show_order import render


def test_an_order_line():
    assert render({"id": 3, "total_cents": 1250, "status": "paid", "discount_cents": 0}) == "Order 3: $12.50 (paid)"
