from datetime import date

import pytest

from patients.phone import is_mobile, normalise
from patients.registry import find, get, register


@pytest.mark.parametrize("raw", ["07700 900123", "+44 7700 900123", "0044 7700 900123", "(07700) 900-123"])
def test_normalise_uk_numbers(raw):
    assert normalise(raw) == "+447700900123"


def test_rejects_foreign_and_short_numbers():
    with pytest.raises(ValueError):
        normalise("+33 6 12 34 56 78")
    with pytest.raises(ValueError):
        normalise("0131 496")


def test_landlines_are_not_mobiles():
    assert is_mobile("07700 900123")
    assert not is_mobile("0131 496 0123")


def test_register_and_find(db):
    patient = register(db, "  Isla Murray ", date(2026, 12, 1), phone="07700 900444", funding="insurer")
    assert get(db, patient.id).phone == "+447700900444"
    assert [p.name for p in find(db, "murr")] == ["Isla Murray"]


def test_register_validates(db):
    with pytest.raises(ValueError):
        register(db, "", date(2026, 12, 1))
    with pytest.raises(ValueError):
        register(db, "Someone", date(2026, 12, 1), funding="nhs")
