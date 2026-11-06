from api.webhooks import parse_payment_event


def test_parse():
    assert parse_payment_event({"id": "x", "amount": "5"}) == ("x", 5)
