import pytest

from till.money import fmt, parse


@pytest.mark.parametrize("pence, text", [(0, "0.00"), (5, "0.05"), (1299, "12.99"), (-250, "-2.50"), (100000, "1000.00")])
def test_fmt(pence, text):
    assert fmt(pence) == text


@pytest.mark.parametrize("text, pence", [("245.10", 24510), ("20", 2000), ("£3.5", 350), ("-1.25", -125), ("0.07", 7)])
def test_parse(text, pence):
    assert parse(text) == pence


@pytest.mark.parametrize("text", ["", "abc", "1.234", "1.2x"])
def test_parse_rejects(text):
    with pytest.raises(ValueError):
        parse(text)
