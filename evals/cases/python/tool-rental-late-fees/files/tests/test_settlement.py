from unittest.mock import patch

from helpers import FRIDAY, MONDAY, NEXT_MONDAY, SATURDAY, THURSDAY, TUESDAY, make_rental
from toolhire import payments
from toolhire.settlement import settle_return


def test_on_time_return_releases_everything():
    settlement = settle_return(make_rental(due_on=TUESDAY), TUESDAY)
    assert settlement.late_days == 0
    assert settlement.captured_cents == 0
    assert settlement.released_cents == 15000


def test_one_day_late_comes_out_of_the_deposit():
    settlement = settle_return(make_rental(due_on=MONDAY), TUESDAY)
    assert settlement.late_fee_cents == 700
    assert settlement.captured_cents == 700
    assert settlement.released_cents == 14300


def test_damage_comes_out_of_the_deposit():
    settlement = settle_return(make_rental(due_on=TUESDAY), TUESDAY, damage_cents=4000)
    assert settlement.captured_cents == 4000
    assert settlement.released_cents == 11000


def test_late_fee_and_damage_add_up():
    settlement = settle_return(make_rental(due_on=MONDAY), TUESDAY, damage_cents=4000)
    assert settlement.captured_cents == 4700


def test_capture_never_exceeds_the_deposit():
    settlement = settle_return(make_rental(due_on=MONDAY, deposit_cents=5000), TUESDAY, damage_cents=9000)
    assert settlement.captured_cents == 5000
    assert settlement.released_cents == 0


def test_nothing_released_when_the_deposit_is_used_up():
    with patch("toolhire.settlement.release_deposit") as release:
        settle_return(make_rental(due_on=MONDAY, deposit_cents=500), TUESDAY)
    release.assert_not_called()


def test_on_time_return_captures_nothing():
    with patch("toolhire.settlement.capture_from_deposit") as capture:
        settle_return(make_rental(due_on=MONDAY), MONDAY)
    capture.assert_not_called()


def test_late_return_captures_the_fee():
    with patch("toolhire.settlement.capture_from_deposit") as capture:
        settle_return(make_rental(rental_id="R-7", due_on=MONDAY), THURSDAY)
    capture.assert_called_once_with("R-7", 2100)


def test_release_is_for_the_remainder():
    with patch("toolhire.settlement.release_deposit") as release:
        settle_return(make_rental(rental_id="R-8", due_on=MONDAY), TUESDAY)
    release.assert_called_once_with("R-8", 14300)


def test_journal_records_both_movements():
    settle_return(make_rental(rental_id="R-9", due_on=MONDAY), TUESDAY)
    kinds = [movement.kind for movement in payments.movements_for("R-9")]
    assert kinds == ["capture", "release"]


def test_monday_return_after_a_friday_due_date():
    settlement = settle_return(make_rental(due_on=FRIDAY), NEXT_MONDAY)
    assert (
        settlement.late_fee_cents == 700,
        "due Friday, back Monday is a single business day",
    )


@patch("toolhire.payments.capture_from_deposit")
def test_saturday_return_after_a_friday_due_date_captures_nothing(capture):
    settle_return(make_rental(due_on=FRIDAY), SATURDAY)
    capture.assert_not_called()
