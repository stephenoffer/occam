import pytest

from common.csvio import CsvError, read_rows, write_rows


def test_read_rows_skips_comments_and_blank_lines(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("# exported 2026-11-01\nworker_id , name\n\nW1, Ann \n")
    rows = read_rows(path, ["worker_id", "name"])
    assert rows == [{"worker_id": "W1", "name": "Ann", "_line": "2"}]


def test_read_rows_names_missing_columns(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("worker_id\nW1\n")
    with pytest.raises(CsvError, match="name"):
        read_rows(path, ["worker_id", "name"])


def test_read_rows_handles_a_byte_order_mark(tmp_path):
    path = tmp_path / "x.csv"
    path.write_bytes("﻿worker_id\nW1\n".encode("utf-8"))
    assert read_rows(path, ["worker_id"])[0]["worker_id"] == "W1"


def test_write_rows_round_trips(tmp_path):
    path = tmp_path / "out" / "y.csv"
    write_rows(path, ["a", "b"], [{"a": "1", "b": "2", "ignored": "3"}])
    assert read_rows(path, ["a", "b"])[0]["b"] == "2"
