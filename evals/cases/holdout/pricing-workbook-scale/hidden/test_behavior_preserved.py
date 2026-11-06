"""Behavior the original evaluator has, through the public Workbook API.

Added after the first holdout run. A run passed every other check here while computing =-(a + b)
as -a + b, and another made long formulas crash. Values come from the untouched starting code.
"""

import json

EXPECTED = {
    "=-(a + b)": -13.0,
    "=-a + b": -7.0,
    "=2 * -(a + b)": -26.0,
    "=-(a - b) * 2": -14.0,
    "=a - b - c": 5.0,
    "=a / b / c": 1.6666666666666667,
    "=a - (b - c)": 9.0,
    "=a + b * c": 16.0,
    "=(a + b) * c": 26.0,
    "=a * -b": -30.0,
    "=--a": 10.0,
    "=-(-(a))": 10.0,
    "=a - -b": 13.0,
    "=-(a * b)": -30.0,
    "=-(a / b)": -3.3333333333333335,
    "=0.1 + 0.2": 0.30000000000000004,
    "=a / 3": 3.3333333333333335,
    "=-a * -b": 30.0,
    "=(a)": 10.0,
    "=a": 10.0,
    "=10": 10.0
}
LONG_FORMULAS = [
    [
        "=a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a",
        500.0
    ],
    [
        "=a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a",
        3000.0
    ],
    [
        "=((((((((((((((((((((((((((((((((((((((((a))))))))))))))))))))))))))))))))))))))))",
        10.0
    ]
]

PROBE = """
import json, sys
from pricemodel import Workbook

results = {}
for formula in json.loads(sys.argv[1]):
    workbook = Workbook()
    for name, value in (("a", 10), ("b", 3), ("c", 2)):
        workbook.set(name, value)
    try:
        workbook.set("d", formula)
        results[formula] = float(workbook.get("d"))
    except Exception as error:
        results[formula] = "raised " + type(error).__name__
print(json.dumps(results))
"""


def evaluate(py, formulas):
    done = py("-c", PROBE, json.dumps(formulas), timeout=30)
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def differences(expected, got):
    return {formula: (want, got.get(formula)) for formula, want in expected.items()
            if not (isinstance(got.get(formula), float) and abs(got[formula] - want) < 1e-9)}


def test_formula_results_unchanged(py):
    wrong = differences(EXPECTED, evaluate(py, list(EXPECTED)))
    assert not wrong, f"formula results changed from the original: {wrong}"


def test_long_formulas_still_work(py):
    expected = dict(LONG_FORMULAS)
    wrong = differences(expected, evaluate(py, list(expected)))
    assert not wrong, f"long formulas changed from the original: { {k[:20]: v for k, v in wrong.items()} }"
