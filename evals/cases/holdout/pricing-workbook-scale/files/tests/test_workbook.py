import json
import subprocess
import sys
from pathlib import Path

import pytest

from pricemodel import CircularReference, FormulaError, Workbook

ROOT = Path(__file__).resolve().parents[1]


def test_numbers_and_formulas():
    wb = Workbook()
    wb.set("price", 120)
    wb.set("cost", "=price * 0.6")
    assert wb.get("cost") == 72.0
    assert wb.names() == ["cost", "price"]


def test_operator_precedence_and_functions():
    wb = Workbook()
    wb.set("a", 2)
    wb.set("b", "=1 + a * 3 - -1")
    wb.set("c", "=SUM(a, b, MAX(1, 5)) / (a + 2)")
    wb.set("d", "=ROUND(10 / 3, 2)")
    assert wb.get("b") == 8.0
    assert wb.get("c") == 3.75
    assert wb.get("d") == 3.33


def test_edit_changes_later_reads():
    wb = Workbook()
    wb.set("a", 1)
    wb.set("b", "=a + 1")
    assert wb.get("b") == 2.0
    wb.set("a", 10)
    assert wb.get("b") == 11.0


def test_unset_cells_read_as_zero_and_can_be_set_later():
    wb = Workbook()
    wb.set("total", "=later + 1")
    assert wb.get("total") == 1.0
    assert wb.get("never_set") == 0.0
    wb.set("later", 4)
    assert wb.get("total") == 5.0


def test_if_only_evaluates_the_branch_it_takes():
    wb = Workbook()
    wb.set("units", 0)
    wb.set("unit_cost", "=100 / units")
    wb.set("safe", "=IF(units = 0, 0, unit_cost)")
    assert wb.get("safe") == 0.0
    wb.set("units", 4)
    assert wb.get("safe") == 25.0


def test_division_by_zero_raises_until_fixed():
    wb = Workbook()
    wb.set("units", 0)
    wb.set("unit_cost", "=100 / units")
    wb.set("doubled", "=unit_cost * 2")
    with pytest.raises(ZeroDivisionError):
        wb.get("doubled")
    wb.set("units", 5)
    assert wb.get("doubled") == 40.0


def test_circular_reference():
    wb = Workbook()
    wb.set("a", "=b + 1")
    wb.set("b", "=a + 1")
    with pytest.raises(CircularReference):
        wb.get("a")
    wb.set("b", 1)
    assert wb.get("a") == 2.0


def test_syntax_error_raises_from_set():
    with pytest.raises(FormulaError):
        Workbook().set("a", "=1 +")


def test_cli_on_sample_model():
    done = subprocess.run(
        [sys.executable, "-m", "pricemodel", str(ROOT / "models" / "sample.json"), "--cell", "margin"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert done.stdout == "margin = 5100.0\n"


def test_cli_prints_every_cell_sorted(tmp_path):
    model = tmp_path / "model.json"
    model.write_text(json.dumps({"cells": {"b": "=a + 1", "a": 1}}))
    done = subprocess.run([sys.executable, "-m", "pricemodel", str(model)],
                          cwd=ROOT, capture_output=True, text=True, check=True)
    assert done.stdout == "a = 1.0\nb = 2.0\n"
