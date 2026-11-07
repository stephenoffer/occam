"""The new-code test's arithmetic: what counts as changed, and what the comparison reports."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import newcode  # noqa: E402


@pytest.mark.parametrize("path, expected", [
    ("app/rules.py", True),
    ("tests/test_rules.py", False),
    ("test_rules.py", False),
    ("rules_test.py", False),
    ("conftest.py", False),
    ("app/__pycache__/rules.pyc", False),
    (".claude/settings.json", False),
    ("testing_tools.py", True),
])
def test_only_product_code_counts_as_changed(path, expected):
    assert newcode.counted(path) is expected


def test_lines_changed_adds_both_directions_and_skips_tests_and_binaries():
    assert newcode.lines_changed("3\t2\tapp/a.py\n10\t0\ttests/test_a.py\n-\t-\tapp/logo.png\n") == 5


def test_a_failed_change_costs_twice_the_largest_passing_one():
    assert newcode.change_cost(5, True, 40) == 5
    assert newcode.change_cost(5, False, 40) == 80


def test_the_gap_is_a_share_of_no_skill_and_positive_when_plugin_code_changes_less():
    assert newcode.spec_gap({"with": [10, 20, 30], "without": [40, 40, 50]}) == pytest.approx(0.5)
    assert newcode.spec_gap({"with": [40], "without": [20]}) == pytest.approx(-1.0)


def test_no_gap_without_both_arms_or_a_baseline():
    assert newcode.spec_gap({"with": [1], "without": []}) is None
    assert newcode.spec_gap({"with": [1], "without": [0]}) is None
