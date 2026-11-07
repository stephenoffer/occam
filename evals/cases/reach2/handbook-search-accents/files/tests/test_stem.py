import pytest

from textproc.stem import stem


@pytest.mark.parametrize("word, expected", [
    ("laptops", "laptop"),
    ("policies", "policy"),
    ("booking", "book"),
    ("booked", "book"),
    ("running", "run"),
    ("billing", "bill"),
    ("classes", "class"),
    ("status", "status"),
    ("analysis", "analysis"),
    ("bus", "bus"),
    ("ring", "ring"),
    ("2026s", "2026s"),
])
def test_light_stemming(word, expected):
    assert stem(word) == expected
