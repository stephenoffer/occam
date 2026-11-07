from appointments.status import TERMINAL, TRANSITIONS, UPCOMING, Status, can_move, parse

import pytest


def test_codes_are_the_practice_system_codes():
    assert [int(s) for s in Status] == [1, 2, 3, 4, 5, 6]


def test_every_status_has_transitions():
    assert set(TRANSITIONS) == set(Status)


def test_finished_appointments_cannot_move():
    for status in TERMINAL:
        for target in Status:
            assert not can_move(status, target)


def test_booked_can_be_confirmed_or_cancelled():
    assert can_move(Status.BOOKED, Status.CONFIRMED)
    assert can_move(Status.BOOKED, Status.CANCELLED)
    assert not can_move(Status.BOOKED, Status.COMPLETED)


def test_upcoming_is_not_terminal():
    assert not UPCOMING & TERMINAL


def test_parse_accepts_cli_spelling():
    assert parse("no-show") is Status.NO_SHOW
    assert parse(" Cancelled ") is Status.CANCELLED
    with pytest.raises(ValueError):
        parse("postponed")
