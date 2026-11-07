import pytest

from common.money import parse_pounds, pounds


def test_pounds():
    assert pounds(3000) == "£30.00"
    assert pounds(123456) == "£1,234.56"
    assert pounds(-550) == "-£5.50"


def test_parse_pounds():
    assert parse_pounds("£30") == 3000
    assert parse_pounds("55.50") == 5550
    with pytest.raises(ValueError):
        parse_pounds("1.005")
    with pytest.raises(ValueError):
        parse_pounds("thirty")
