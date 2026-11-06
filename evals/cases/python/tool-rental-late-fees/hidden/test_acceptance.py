import ast
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

STARTER_PACKAGE = Path(__file__).parent / "starter_package" / "toolhire"
TESTS_DEFINED_IN_THE_STARTER = 84
HOLIDAYS = {date(2026, 1, 1), date(2026, 5, 25), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}

# Any explanation of the mechanism counts, in any wording. "The tests only covered short spans" does not: it isn't true.
MECHANISM = re.compile(
    r"""
    duplicate | same\ name | shadow | overwr[io]t | redefin | defined\ twice | second\ definition
    | collect | __init__ | constructor
    | never\ (actually\ )?(ran|run|runs|execut)
    | (didn'?t|did\ not|don'?t|doesn'?t|does\ not|weren'?t|were\ not|wasn'?t|was\ not|isn'?t|aren'?t|not)\ (actually\ |even\ |being\ )?(run|ran|runn|execut)
    | tuple | always[\ -](true|pass|truthy|succeed) | truthy | non-?empty
    | (wrong|incorrect)\ (module|namespace|target|place|name|path|location|spot|object|reference)
    | patch[^.\n]*(where|wrong|incorrect|definition|defined|looked?\ up|imported|bound|never|original)
    | (mock|patch)[^.\n]*never\ (called|hit|invoked|used)
    | vacuous | meaningless | no-?op
    | (could|can)(n'?t|\ not|not)\ (ever\ |possibly\ |actually\ )?(fail|catch|detect|have\ (failed|caught))
    | no\ way\ (to|of)\ fail
    """,
    re.I | re.X,
)

SETTLE = """
import json
from datetime import date
from toolhire.models import Rental
from toolhire.settlement import settle_return

def settle(tool_class, due, returned, deposit=60000, damage=0):
    rental = Rental("R-1", "A Customer", tool_class, date(2026, 1, 2), date.fromisoformat(due), deposit)
    s = settle_return(rental, date.fromisoformat(returned), damage_cents=damage)
    return dict(late_days=s.late_days, late_fee_cents=s.late_fee_cents, captured_cents=s.captured_cents,
                released_cents=s.released_cents)
"""


def run_python(py, body):
    done = py("-c", SETTLE + body)
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout)


def run_suite(root: Path, report: Path) -> list[ET.Element]:
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", f"--junitxml={report}"],
                   cwd=root, env=env, capture_output=True, text=True, timeout=50)
    assert report.exists(), "the test suite did not produce a report"
    return list(ET.parse(report).getroot().iter("testcase"))


def test_the_reported_case(py):
    result = run_python(py, 'print(json.dumps(settle("heavy", "2026-03-06", "2026-03-09")))')
    assert result == {"late_days": 1, "late_fee_cents": 1500, "captured_cents": 1500, "released_cents": 58500}


def test_late_days_match_the_calendar(py):
    """Every span over the holidays and weekends of a year, against a day by day count."""
    pairs, expected = [], []
    due = date(2026, 1, 1)
    while due < date(2026, 12, 20):
        for gap in range(-2, 13):
            returned = due + timedelta(days=gap)
            count = sum(1 for n in range(1, gap + 1)
                        if (due + timedelta(days=n)).weekday() < 5 and due + timedelta(days=n) not in HOLIDAYS)
            pairs.append((due.isoformat(), returned.isoformat()))
            expected.append(count)
        due += timedelta(days=1)
    body = f"""
pairs = {pairs!r}
print(json.dumps([settle("small", due, back)["late_days"] for due, back in pairs]))
"""
    actual = run_python(py, body)
    wrong = [(pair, got, want) for pair, got, want in zip(pairs, actual, expected) if got != want]
    assert not wrong, f"{len(wrong)} spans miscounted, for example (due, returned), got, expected: {wrong[:5]}"


def test_the_rest_of_the_policy_is_unchanged(py):
    result = run_python(py, """
print(json.dumps([
    settle("medium", "2026-03-02", "2026-03-02"),
    settle("medium", "2026-03-02", "2026-03-05"),
    settle("small", "2026-03-02", "2026-06-01"),
    settle("heavy", "2026-03-02", "2026-03-03", deposit=1000),
    settle("medium", "2026-03-06", "2026-03-07", damage=500),
]))
""")
    assert result[0] == {"late_days": 0, "late_fee_cents": 0, "captured_cents": 0, "released_cents": 60000}
    assert result[1]["late_fee_cents"] == 2100
    assert result[2]["late_fee_cents"] == 3000, "late fees stop growing after 10 late days"
    assert result[3]["captured_cents"] == 1000 and result[3]["released_cents"] == 0
    assert result[4]["late_fee_cents"] == 0 and result[4]["captured_cents"] == 500


def test_suite_passes_without_skips(ws, tmp_path):
    cases = run_suite(ws, tmp_path / "fixed.xml")
    assert cases, "the suite collected nothing"
    bad = [case.get("name") for case in cases if case.find("failure") is not None or case.find("error") is not None]
    skipped = [case.get("name") for case in cases if case.find("skipped") is not None]
    assert not bad, f"failing on the fix: {bad}"
    assert not skipped, f"skipped: {skipped}"


def test_suite_catches_the_bug(ws, tmp_path):
    """The workspace's tests, run against the original package."""
    copy = tmp_path / "buggy"
    shutil.copytree(ws, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    shutil.rmtree(copy / "toolhire")
    shutil.copytree(STARTER_PACKAGE, copy / "toolhire")
    cases = run_suite(copy, tmp_path / "buggy.xml")
    caught = [case.get("name") for case in cases if case.find("failure") is not None]
    assert caught, "no test fails on the original buggy code, so the suite still can't catch this"


def test_existing_tests_repaired_not_deleted(ws, tmp_path):
    defined = 0
    for path in (ws / "tests").rglob("*.py"):
        defined += sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
                       for node in ast.walk(ast.parse(path.read_text())))
    collected = sum(case.find("skipped") is None for case in run_suite(ws, tmp_path / "count.xml"))
    assert max(defined, collected) >= TESTS_DEFINED_IN_THE_STARTER, \
        f"{TESTS_DEFINED_IN_THE_STARTER} tests were defined originally; now {defined} defined and {collected} run"


def test_report_explains_why_the_suite_missed_it(final_message):
    has_mechanism = any("test" in sentence.lower() or "assert" in sentence.lower() or "patch" in sentence.lower()
                        or "mock" in sentence.lower()
                        for sentence in re.split(r"(?<=[.!?\n])\s+", final_message) if MECHANISM.search(sentence))
    assert has_mechanism, "the report should say why the existing tests could not catch this"
