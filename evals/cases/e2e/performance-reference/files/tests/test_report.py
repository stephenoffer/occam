from report import top_customers


def test_top():
    rows = [{"customer": "a", "amount": 1}, {"customer": "b", "amount": 5}, {"customer": "a", "amount": 2}]
    assert top_customers(rows, 1) == ["b"]
