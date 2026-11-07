"""Payslip lines for one worker's week."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from common.money import pennies, plain
from payroll.hours import WeekHours
from payroll.rates import Rate


@dataclass
class Payslip:
    worker_id: str
    name: str
    week: str
    regular_hours: Decimal
    overtime_hours: Decimal
    basic_pay: Decimal
    overtime_pay: Decimal
    allowances: Decimal = Decimal(0)
    notes: list[str] = field(default_factory=list)

    @property
    def gross(self) -> Decimal:
        return self.basic_pay + self.overtime_pay + self.allowances

    def as_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "week": self.week,
            "regular_hours": f"{self.regular_hours:.2f}",
            "overtime_hours": f"{self.overtime_hours:.2f}",
            "basic_pay": plain(self.basic_pay),
            "overtime_pay": plain(self.overtime_pay),
            "allowances": plain(self.allowances),
            "gross": plain(self.gross),
            "notes": list(self.notes),
        }


def build_payslip(hours: WeekHours, rate: Rate, allowances: Decimal = Decimal(0)) -> Payslip:
    """Basic and overtime pay are each rounded to the penny, as the bureau's import expects."""
    return Payslip(
        worker_id=hours.worker_id,
        name=rate.name,
        week=hours.week.isoformat(),
        regular_hours=hours.regular,
        overtime_hours=hours.overtime,
        basic_pay=pennies(hours.regular * rate.base_hourly),
        overtime_pay=pennies(hours.overtime * rate.overtime_hourly),
        allowances=pennies(allowances),
    )
