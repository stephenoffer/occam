"""The fee schedule, read from billing/fees.ini."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FEES = Path(__file__).with_name("fees.ini")


@dataclass(frozen=True)
class FeeSchedule:
    treatment_pence: int
    extended_treatment_pence: int
    missed_appointment_pence: int
    standard_minutes: int

    def treatment_for(self, minutes: int) -> int:
        return self.extended_treatment_pence if minutes > self.standard_minutes else self.treatment_pence


def load_fees(path: str | Path = DEFAULT_FEES) -> FeeSchedule:
    config = configparser.ConfigParser(inline_comment_prefixes=(";",))
    if not config.read(path):
        raise FileNotFoundError(f"no fee schedule at {path}")
    fees = config["fees"]
    schedule = FeeSchedule(
        treatment_pence=fees.getint("treatment_fee_pence"),
        extended_treatment_pence=fees.getint("extended_treatment_fee_pence"),
        missed_appointment_pence=fees.getint("missed_appointment_fee_pence"),
        standard_minutes=config.getint("treatment", "standard_minutes", fallback=45),
    )
    for name, value in vars(schedule).items():
        if value < 0:
            raise ValueError(f"{name} can't be negative")
    return schedule
