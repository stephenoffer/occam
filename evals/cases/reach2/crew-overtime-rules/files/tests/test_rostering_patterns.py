from datetime import date

import pytest

from common.csvio import read_rows
from rostering.roster import FIELDS, append_rows, expand


def test_weekly_pattern_follows_weekdays():
    rows = expand("long-days", "W1", "MLT", date(2026, 11, 4), 1)
    assert [row["date"] for row in rows] == ["2026-11-04", "2026-11-05", "2026-11-09", "2026-11-10"]
    assert rows[0]["start"] == "07:00" and rows[0]["unpaid_break_minutes"] == "30"


def test_cycle_pattern_counts_from_the_start_date():
    rows = expand("four-on-four-off", "W1", "NWK", date(2026, 11, 4), 2)
    assert [row["date"][-2:] for row in rows] == ["04", "05", "06", "07", "12", "13", "14", "15"]


def test_unknown_pattern_lists_the_known_ones():
    with pytest.raises(KeyError, match="earlies"):
        expand("nights", "W1", "NWK", date(2026, 11, 2), 1)


def test_append_keeps_the_file_sorted(tmp_path):
    path = tmp_path / "plan.csv"
    append_rows(path, expand("days", "W2", "QSY", date(2026, 11, 2), 1))
    total = append_rows(path, expand("weekend-cover", "VACANT", "HBR", date(2026, 11, 2), 1))
    rows = read_rows(path, FIELDS)
    assert total == 7
    assert rows[0]["site"] == "HBR"
