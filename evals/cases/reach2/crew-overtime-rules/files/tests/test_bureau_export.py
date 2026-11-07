import json

import pytest

from exports.bureau import LINE_WIDTH, BureauError, records, write

PAYROLL = {
    "week": "2026-11-02",
    "payslips": [
        {"worker_id": "W101", "regular_hours": "40.00", "overtime_hours": "6.25", "basic_pay": "720.00",
         "overtime_pay": "168.75", "allowances": "12.50", "gross": "901.25"},
        {"worker_id": "W105", "regular_hours": "22.50", "overtime_hours": "0.00", "basic_pay": "256.50",
         "overtime_pay": "0.00", "allowances": "0.00", "gross": "256.50"},
    ],
}


def test_records_are_fixed_width():
    lines = records(PAYROLL)
    assert all(len(line) == LINE_WIDTH for line in lines)
    assert lines[0].startswith("H2026-11-02000002")
    assert lines[1].startswith("DW101    0040000006250000720000000168750001250000090125")
    assert lines[-1].startswith("T000000115775")


def test_fractions_of_a_penny_are_refused():
    bad = json.loads(json.dumps(PAYROLL))
    bad["payslips"][0]["gross"] = "901.255"
    with pytest.raises(BureauError):
        records(bad)


def test_write_uses_crlf(tmp_path):
    source = tmp_path / "payslips.json"
    source.write_text(json.dumps(PAYROLL))
    out = tmp_path / "PAYIMP.txt"
    assert write(source, out) == 4
    assert out.read_bytes().count(b"\r\n") == 4
