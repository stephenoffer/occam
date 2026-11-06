from datetime import date
from decimal import Decimal

from tidewater.domain.adjustments.conversion import conversion_rate
from tidewater.domain.adjustments.registry import apply_adjustments, schedule


def amounts(lane, currency="USD", subtotal="1000"):
    return {line.code: line.amount for line in apply_adjustments(lane, currency, Decimal(subtotal), date(2026, 10, 20))}


def test_every_lane_pays_security_and_documentation():
    assert amounts("SIN-LAX")["SEC"] == Decimal("45.00")
    assert amounts("SIN-LAX")["DOC"] == Decimal("25.00")


def test_percentage_levy():
    assert amounts("SIN-RTM", subtotal="2000")["PSS"] == Decimal("50.00")


def test_contract_converted_levy_in_eur():
    assert amounts("SIN-RTM", "EUR")["SEC"] == Decimal("40.50")


def test_canal_fee_in_usd():
    assert amounts("YOK-SIN")["CNL"] == Decimal("202.71")


def test_conversion_by_contract_family():
    assert conversion_rate("contract", "USD", "GBP", date(2026, 10, 20)) == Decimal("0.800000")


def test_spot_levy_uses_the_date():
    february = apply_adjustments("RTM-NYC", "GBP", Decimal("1000"), date(2026, 2, 14))
    august = apply_adjustments("RTM-NYC", "GBP", Decimal("1000"), date(2026, 8, 20))
    assert {line.code: line.amount for line in february}["ECA"] == Decimal("103.04")
    assert {line.code: line.amount for line in august}["ECA"] == Decimal("103.64")


def test_schedule_loads():
    assert {entry.code for entry in schedule()} >= {"SEC", "DOC", "PSS", "CNL"}
