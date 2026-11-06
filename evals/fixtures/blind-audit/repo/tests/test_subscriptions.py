from __future__ import annotations

from datetime import date

from subledger import store
from subledger.services import billing, subscriptions


def _subscribe(conn, gateway, customer, plan_id="starter_monthly", trial=False, today=date(2026, 3, 1), **kwargs):
    return subscriptions.create_subscription(
        conn, gateway, tenant_id=1, customer=customer, plan=store.get_plan(conn, plan_id),
        trial=trial, today=today, **kwargs,
    )


def test_trial_issues_no_invoice(conn, gateway, us_customer):
    sub = _subscribe(conn, gateway, us_customer, trial=True)
    assert (sub.status, sub.current_period_end) == ("trialing", "2026-03-14")
    assert gateway.charges == []


def test_paid_signup_charges_for_each_seat(conn, gateway, us_customer):
    sub = _subscribe(conn, gateway, us_customer, quantity=3)
    assert (sub.status, sub.current_period_end) == ("active", "2026-03-31")
    assert gateway.charges[0]["amount"] == 8700


def test_coupon_redemption_is_counted(conn, gateway, us_customer):
    store.insert_coupon(conn, 1, "HALF", percent_off=50, max_redemptions=5)
    conn.commit()
    _subscribe(conn, gateway, us_customer, coupon_code="HALF")
    assert gateway.charges[0]["amount"] == 1450
    assert store.get_coupon(conn, 1, "HALF").redeemed_count == 1


def test_upgrade_and_downgrade(conn, gateway, us_customer):
    sub = _subscribe(conn, gateway, us_customer)
    growth, starter = store.get_plan(conn, "growth_monthly"), store.get_plan(conn, "starter_monthly")
    updated, invoice = subscriptions.change_plan(
        conn, gateway, tenant_id=1, subscription_id=sub.id, new_plan=growth, today=date(2026, 3, 11)
    )
    assert (updated.plan_id, updated.price_cents) == ("growth_monthly", 9900)
    assert gateway.charges[-1]["amount"] == invoice.total_cents
    updated, invoice = subscriptions.change_plan(conn, gateway, tenant_id=1, subscription_id=sub.id, new_plan=starter)
    assert invoice is None
    assert (updated.plan_id, updated.pending_plan_id) == ("growth_monthly", "starter_monthly")


def test_renewal_moves_the_period_forward(conn, gateway, us_customer):
    sub = _subscribe(conn, gateway, us_customer)
    assert billing.renew_subscription(conn, gateway, sub, today=date(2026, 4, 1)).total_cents == 2900
    assert store.get_subscription(conn, 1, sub.id).current_period_end == "2026-04-30"


def test_renewal_honours_cancel_at_period_end(conn, gateway, us_customer):
    sub = _subscribe(conn, gateway, us_customer)
    flagged = subscriptions.cancel_subscription(conn, tenant_id=1, subscription_id=sub.id)
    assert (flagged.status, flagged.cancel_at_period_end) == ("active", 1)
    assert billing.renew_subscription(conn, gateway, flagged, today=date(2026, 4, 1)) is None
    assert store.get_subscription(conn, 1, sub.id).status == "canceled"
