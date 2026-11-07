"""The bureau's fixed-width import (their spec PAYIMP v2, 64 characters a line).

    H  week(10)  record count(6)
    D  worker(8) regular hours x100(6) overtime hours x100(6) basic p(9) overtime p(9) allowances p(7) gross p(9)
    T  total gross p(12)

Hours and amounts come straight from payroll's payslips; nothing is recalculated here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

LINE_WIDTH = 64


class BureauError(ValueError):
    pass


def _num(value: str, width: int, scale: int = 100) -> str:
    number = Decimal(value) * scale
    if number != number.to_integral_value() or number < 0:
        raise BureauError(f"{value} can't be sent as a whole number of hundredths")
    text = str(int(number))
    if len(text) > width:
        raise BureauError(f"{value} is too large for a {width}-digit field")
    return text.rjust(width, "0")


def _pad(text: str) -> str:
    if len(text) > LINE_WIDTH:
        raise BureauError(f"record longer than {LINE_WIDTH}: {text!r}")
    return text.ljust(LINE_WIDTH)


def records(payroll_json: dict) -> list[str]:
    slips = payroll_json["payslips"]
    lines = [_pad(f"H{payroll_json['week']}{len(slips):06d}")]
    total = Decimal(0)
    for slip in slips:
        if len(slip["worker_id"]) > 8:
            raise BureauError(f"worker id {slip['worker_id']} is longer than 8")
        lines.append(_pad("D" + slip["worker_id"].ljust(8)
                          + _num(slip["regular_hours"], 6) + _num(slip["overtime_hours"], 6)
                          + _num(slip["basic_pay"], 9) + _num(slip["overtime_pay"], 9)
                          + _num(slip["allowances"], 7) + _num(slip["gross"], 9)))
        total += Decimal(slip["gross"])
    lines.append(_pad("T" + _num(str(total), 12)))
    return lines


def write(payslips_path: str | Path, out: str | Path) -> int:
    data = json.loads(Path(payslips_path).read_text(encoding="utf-8"))
    lines = records(data)
    Path(out).write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return len(lines)
