from datetime import date
from decimal import Decimal

from payroll.hours import WeekHours
from payroll.payslip import build_payslip
from payroll.rates import Rate


def test_payslip_lines_round_separately():
    hours = WeekHours("W1", date(2026, 11, 2), Decimal("39.75"), Decimal("0"))
    slip = build_payslip(hours, Rate("W1", "Ann", "skilled", Decimal("21.25")))
    assert slip.basic_pay == Decimal("844.69")
    assert slip.gross == Decimal("844.69")


def test_overtime_is_paid_at_the_multiplier():
    hours = WeekHours("W1", date(2026, 11, 2), Decimal(40), Decimal("2.5"))
    slip = build_payslip(hours, Rate("W1", "Ann", "skilled", Decimal("20")), allowances=Decimal("12.5"))
    assert slip.overtime_pay == Decimal("75.00")
    assert slip.as_dict()["gross"] == "887.50"
    assert slip.as_dict()["overtime_hours"] == "2.50"
