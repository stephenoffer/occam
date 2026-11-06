import datetime as dt
import json
from decimal import Decimal

import pytest

from toolhire import desk
from toolhire.desk import (
    Asset,
    Booking,
    Category,
    ConflictError,
    Customer,
    NotFoundError,
    ShopCalendar,
    ShopState,
    StateError,
    ValidationError,
    money,
    money_str,
    parse_date,
    render_rows,
    split_evenly,
)


def d(text):
    return parse_date(text)


@pytest.fixture
def state():
    shop = ShopState("0.20")
    shop.calendar = ShopCalendar(holidays={d("2026-03-20")})
    shop.catalog.add_category(Category("DRILL", "Drills", "18.00", "72.00", "50.00", 90, 1))
    shop.catalog.add_category(Category("MIXER", "Mixers", "24.00", "96.00", "80.00", 60, 0))
    shop.catalog.add_asset(Asset("DR-1", "DRILL", "SDS drill", "240.00", acquired_on="2026-01-05"))
    shop.catalog.add_asset(Asset("DR-2", "DRILL", "Big SDS drill", "320.00", acquired_on="2026-01-05"))
    shop.catalog.add_asset(Asset("MX-1", "MIXER", "Mixer", "60.00", acquired_on="2025-10-01", last_serviced_on="2026-01-01"))
    shop.customers.add(Customer("C-1", "Pat", "pat@example.invalid"))
    shop.customers.add(Customer("C-2", "Oakfield", "ops@oakfield.invalid", "trade", "1000.00"))
    shop.customers.add(Customer("C-3", "Northgate", "ops@northgate.invalid", "contractor", "1000.00"))
    return shop


def test_money_rounds_half_up():
    assert money("1.005") == Decimal("1.01")
    assert money_str("3") == "3.00"


def test_money_refuses_floats_and_rubbish():
    with pytest.raises(ValidationError):
        money(1.5)
    with pytest.raises(ValidationError):
        money("a lot")


def test_split_evenly_adds_back_up():
    shares = split_evenly("10.00", 3)
    assert shares == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert sum(shares) == Decimal("10.00")


def test_calendar_skips_sundays_and_holidays():
    calendar = ShopCalendar(holidays={d("2026-03-20")})
    assert not calendar.is_open(d("2026-03-08"))
    assert not calendar.is_open(d("2026-03-20"))
    assert calendar.open_days_between(d("2026-03-06"), d("2026-03-09")) == 2
    assert calendar.next_open_day(d("2026-03-19")) == d("2026-03-21")
    assert calendar.add_open_days(d("2026-03-06"), 2) == d("2026-03-09")


def test_category_rejects_a_week_dearer_than_seven_days():
    with pytest.raises(ValidationError):
        Category("X", "X", "10.00", "71.00", "0.00")


def test_customer_rejects_a_malformed_email():
    with pytest.raises(ValidationError):
        Customer("C-9", "Nope", "not an address")


def test_catalog_search_and_retire(state):
    assert [a.tag for a in state.catalog.search("big")] == ["DR-2"]
    state.catalog.retire("DR-2")
    assert [a.tag for a in state.catalog.assets_in("DRILL")] == ["DR-1"]
    with pytest.raises(NotFoundError):
        state.catalog.asset("NOPE")


def test_hire_charge_mixes_weeks_and_odd_days(state):
    drill = state.catalog.category("DRILL")
    assert desk.hire_charge(drill, 1, desk.TIERS["walk_in"]) == Decimal("18.00")
    assert desk.hire_charge(drill, 6, desk.TIERS["walk_in"]) == Decimal("72.00")
    assert desk.hire_charge(drill, 7, desk.TIERS["walk_in"]) == Decimal("90.00")
    assert desk.hire_charge(drill, 5, desk.TIERS["walk_in"]) == Decimal("72.00")
    assert desk.hire_charge(drill, 6, desk.TIERS["trade"]) == Decimal("64.80")


def test_quote_adds_delivery_waiver_and_deposit(state):
    quote = desk.build_quote(state, "DRILL", d("2026-03-02"), d("2026-03-09"), "C-2", "local", True)
    assert quote.days == 6
    assert quote.to_dict() == {
        "category": "DRILL",
        "start": "2026-03-02",
        "end": "2026-03-09",
        "days": 6,
        "hire": "64.80",
        "delivery": "15.00",
        "waiver": "5.18",
        "deposit": "25.00",
        "total_due_today": "109.98",
    }


def test_booking_needs_a_free_asset(state):
    desk.reserve(state, "C-1", "MIXER", d("2026-03-02"), d("2026-03-06"))
    with pytest.raises(ConflictError):
        desk.reserve(state, "C-2", "MIXER", d("2026-03-05"), d("2026-03-08"))
    desk.reserve(state, "C-2", "MIXER", d("2026-03-06"), d("2026-03-08"))


def test_booking_dates_must_make_sense():
    with pytest.raises(ValidationError):
        Booking("B-9", "C-1", "DRILL", "2026-03-06", "2026-03-06")


def test_cancelled_booking_frees_the_asset(state):
    booking = desk.reserve(state, "C-1", "MIXER", d("2026-03-02"), d("2026-03-06"))
    assert desk.free_count(state, "MIXER", d("2026-03-03"), d("2026-03-04")) == 0
    desk.cancel_booking(state, booking.id)
    assert desk.free_count(state, "MIXER", d("2026-03-03"), d("2026-03-04")) == 1
    with pytest.raises(StateError):
        desk.cancel_booking(state, booking.id)


def test_checkout_charges_and_takes_deposit(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    assert rental.id == "R-1"
    assert rental.hire_charge == Decimal("72.00")
    assert rental.deposit_paid == Decimal("50.00")
    assert state.catalog.asset("DR-1").status == "on_hire"
    with pytest.raises(StateError):
        desk.checkout(state, "C-2", "DR-1", d("2026-03-02"), d("2026-03-06"))


def test_blocked_customer_cannot_hire(state):
    state.customers.block("C-1", "bounced cheque")
    with pytest.raises(StateError):
        desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))


def test_credit_limit_stops_a_hire(state):
    state.customers.get("C-2").credit_limit = Decimal("10.00")
    with pytest.raises(StateError):
        desk.checkout(state, "C-2", "DR-1", d("2026-03-02"), d("2026-03-06"))


def test_on_time_return_refunds_the_deposit(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    settlement = desk.checkin(state, rental.id, d("2026-03-06"))
    assert settlement.late_fee == Decimal("0.00")
    assert settlement.refund == Decimal("50.00")
    assert state.catalog.asset("DR-1").status == "available"


def test_late_return_charges_after_grace(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    settlement = desk.settle_return(state, rental, d("2026-03-10"))
    # Sat 7, Mon 9, Tue 10 are open; Sunday is not. One grace day leaves two days at 27.00.
    assert settlement.late_days == 2
    assert settlement.late_fee == Decimal("54.00")
    assert settlement.deposit_applied == Decimal("50.00")
    assert settlement.balance_due == Decimal("4.00")


def test_late_fee_is_capped_at_replacement_value(state):
    rental = desk.checkout(state, "C-1", "MX-1", d("2026-03-02"), d("2026-03-06"))
    assert desk.late_fee(state, rental, d("2026-04-30")) == Decimal("60.00")


def test_trade_customers_get_extra_grace(state):
    rental = desk.checkout(state, "C-2", "DR-1", d("2026-03-02"), d("2026-03-06"))
    assert desk.billable_late_days(state, rental, d("2026-03-10")) == 1


def test_extension_moves_the_due_date_and_recharges(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.extend_rental(state, rental.id, d("2026-03-13"), "Sam")
    assert desk.effective_due(rental) == d("2026-03-13")
    assert rental.hire_charge == Decimal("144.00")
    assert desk.billable_late_days(state, rental, d("2026-03-13")) == 0
    with pytest.raises(ValidationError):
        desk.extend_rental(state, rental.id, d("2026-03-13"), "Sam")


def test_damage_downgrades_the_asset(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    settlement = desk.checkin(state, rental.id, d("2026-03-06"), "repairable")
    assert settlement.damage == Decimal("60.00")
    assert state.catalog.asset("DR-1").condition == "fair"


def test_disputed_hire_cannot_be_returned_until_resolved(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.mark_disputed(state, rental.id, "says it was faulty")
    with pytest.raises(StateError):
        desk.checkin(state, rental.id, d("2026-03-06"))
    desk.resolve_dispute(state, rental.id)
    desk.checkin(state, rental.id, d("2026-03-06"))


def test_reminder_clock_ignores_extensions(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.extend_rental(state, rental.id, d("2026-03-20"), "Sam")
    assert desk.days_overdue(rental, d("2026-03-14")) == 8
    assert desk.reminder_stage(8) == "firm"
    assert "around 144.00" in desk.reminder_letter(state, rental, d("2026-03-14"))


def test_service_due_counts_from_last_service(state):
    mixer = state.catalog.asset("MX-1")
    assert desk.service_due_on(state, mixer) == d("2026-03-02")
    assert [a.tag for a in desk.assets_due_service(state, d("2026-03-02"))] == ["MX-1"]


def test_work_order_takes_the_asset_out_and_back(state):
    order = desk.open_work_order(state, "MX-1", d("2026-03-02"), "drum bearing")
    assert state.catalog.asset("MX-1").status == "in_service"
    desk.close_work_order(state, order.id, d("2026-03-04"), "35.50", "new bearing")
    mixer = state.catalog.asset("MX-1")
    assert (mixer.status, mixer.last_serviced_on) == ("available", d("2026-03-04"))
    assert desk.service_cost_of(state, "MX-1") == Decimal("35.50")


def test_invoice_has_hire_late_and_tax_but_no_deposit(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.checkin(state, rental.id, d("2026-03-10"))
    invoice = desk.invoice_for_rental(state, rental.id, d("2026-03-10"))
    assert [line.amount for line in invoice.lines] == [Decimal("72.00"), Decimal("54.00")]
    assert invoice.tax == Decimal("25.20")
    assert invoice.total == Decimal("151.20")
    with pytest.raises(ConflictError):
        desk.invoice_for_rental(state, rental.id, d("2026-03-10"))


def test_credit_note_negates_the_invoice(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.checkin(state, rental.id, d("2026-03-06"))
    invoice = desk.invoice_for_rental(state, rental.id, d("2026-03-06"))
    credit = desk.credit_note(state, invoice.number, d("2026-03-07"), "Goodwill")
    assert credit.total == -invoice.total
    assert "CREDIT NOTE" in desk.render_invoice(state, credit)


def test_state_round_trips(state, tmp_path):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.extend_rental(state, rental.id, d("2026-03-10"), "Sam")
    path = tmp_path / "shop.json"
    desk.save_state(state, path)
    again = desk.load_state(path)
    assert again.to_dict() == state.to_dict()
    assert desk.effective_due(again.rental(rental.id)) == d("2026-03-10")


def test_old_state_files_are_upgraded(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "version": 1,
        "categories": [{"code": "DRILL", "name": "Drills", "daily_rate": "18.00", "weekly_rate": "72.00", "deposit": "50.00"}],
        "assets": [{"tag": "DR-1", "category": "DRILL", "description": "SDS", "replacement_value": "240.00"}],
        "customers": [{"id": "C-1", "name": "Pat", "email": "pat@example.invalid"}],
        "rentals": [{"id": "R-1", "hirer": "C-1", "asset": "DR-1", "started_on": "2026-03-02", "due_on": "2026-03-06", "deposit": "50.00"}],
    }))
    rental = desk.load_state(path).rental("R-1")
    assert (rental.customer, rental.deposit_paid) == ("C-1", Decimal("50.00"))


def test_render_rows_formats():
    rows = [{"a": "x", "b": "1"}, {"a": "yy", "b": "22"}]
    assert render_rows(rows, ("a", "b"), "csv") == "a,b\nx,1\nyy,22"
    assert json.loads(render_rows(rows, ("a", "b"), "json")) == rows
    assert render_rows(rows, ("a", "b"), "table").splitlines()[0].split() == ["a", "b"]
    assert render_rows([], ("a", "b"), "table") == "(nothing to report)"


def test_utilization_counts_days_out(state):
    rental = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.checkin(state, rental.id, d("2026-03-12"))
    rows = {row["category"]: row for row in desk.utilization_rows(state, d("2026-03-31"), 30)}
    assert rows["DRILL"] == {"category": "DRILL", "assets": 2, "days_out": 10, "utilization_percent": "16.7"}


def test_deposit_rows_only_list_what_is_still_held(state):
    first = desk.checkout(state, "C-1", "DR-1", d("2026-03-02"), d("2026-03-06"))
    desk.checkout(state, "C-3", "DR-2", d("2026-03-02"), d("2026-03-06"))
    assert desk.deposit_rows(state) == [
        {"rental": first.id, "customer": "C-1", "asset": "DR-1", "deposit_held": "50.00"}
    ]


def test_customer_and_fleet_rows(state):
    desk.checkout(state, "C-2", "DR-1", d("2026-03-02"), d("2026-03-06"))
    row = next(r for r in desk.customer_rows(state) if r["customer"] == "C-2")
    assert row["outstanding"] == "64.80"
    fleet = {r["category"]: r for r in desk.fleet_rows(state)}
    assert fleet["DRILL"]["replacement_value"] == "560.00"
