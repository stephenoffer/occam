import pytest

from toolhire.payments import JOURNAL, capture_from_deposit, movements_for, release_deposit


def test_capture_is_journalled():
    capture_from_deposit("R-1", 100)
    assert JOURNAL[-1].kind == "capture"


def test_release_is_journalled():
    release_deposit("R-1", 100)
    assert JOURNAL[-1].kind == "release"


def test_capture_must_be_positive():
    with pytest.raises(ValueError):
        capture_from_deposit("R-1", 0)


def test_release_must_be_positive():
    with pytest.raises(ValueError):
        release_deposit("R-1", -5)


def test_movements_are_per_rental():
    capture_from_deposit("R-1", 100)
    release_deposit("R-2", 200)
    assert [movement.cents for movement in movements_for("R-2")] == [200]
