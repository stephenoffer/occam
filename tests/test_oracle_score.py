"""The oracle scorer, on a tiny fixture: a calc module with one planted defect and one oracle for it."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import oracle_score
import pytest

needs_sandbox = pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="sandbox-exec is macOS only")

CALC = "def add(a, b):\n    return a - b\n\n\ndef double(a):\n    return a * 2\n"
ORIGINAL_TESTS = """from calc import double


def test_double():
    assert double(2) == 4


def test_double_zero():
    assert double(0) == 0
"""
ORACLE = """from calc import add


def test_calc_01():
    if add(1, 2) != 3:
        raise AssertionError("defect: add subtracts")
"""
ANSWERS = [{"id": "calc-01", "severity": "high"}, {"id": "calc-02", "severity": "low"}, {"id": "calc-03", "severity": "critical"}]
NOT_TESTABLE = [{"id": "calc-03", "reason": "only visible in a notebook"}]

FIX = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,5 +1,5 @@
 def add(a, b):
-    return a - b
+    return a + b
 
 
 def double(a):
"""
BREAK_DOUBLE = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -3,4 +3,4 @@ def add(a, b):
 
 
 def double(a):
-    return a * 2
+    raise ValueError("no")
"""
HIDE_THE_BREAK = BREAK_DOUBLE + """diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -4,6 +4,4 @@ from calc import double
 def test_double():
-    assert double(2) == 4
+    assert True


-def test_double_zero():
-    assert double(0) == 0
"""
DOES_NOT_APPLY = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,5 +1,5 @@
 def something_else(a, b):
-    return a * b
+    return a + b
 
 
 def double(a):
"""


@pytest.fixture
def fixture_dir(tmp_path):
    fixture = tmp_path / "fixtures" / "tiny"
    (fixture / "repo" / "tests").mkdir(parents=True)
    (fixture / "oracles").mkdir()
    (fixture / "repo" / "calc.py").write_text(CALC)
    (fixture / "repo" / "tests" / "test_calc.py").write_text(ORIGINAL_TESTS)
    (fixture / "oracles" / "test_calc.py").write_text(ORACLE)
    (fixture / "oracles" / "NOT_TESTABLE.json").write_text(json.dumps(NOT_TESTABLE))
    (fixture / "ANSWERS.json").write_text(json.dumps(ANSWERS))
    return fixture


def write_diff(tmp_path, text, name="attempt"):
    path = tmp_path / f"{name}.diff"
    path.write_text(text)
    return path


def tree(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


@needs_sandbox
def test_calibration_is_clean_when_every_oracle_fails_for_its_reason(fixture_dir):
    report = oracle_score.calibrate(fixture_dir, 60)
    assert report["oracles"] == 1
    assert report["not_testable"] == {"calc-03": "only visible in a notebook"}
    assert (report["passes_on_start"], report["fails_for_another_reason"], report["no_oracle"]) == ([], [], [])


@needs_sandbox
def test_calibration_names_an_oracle_that_passes_on_the_starting_code(fixture_dir):
    (fixture_dir / "oracles" / "test_more.py").write_text("def test_calc_02():\n    pass\n")
    assert oracle_score.calibrate(fixture_dir, 60)["passes_on_start"] == ["calc-02"]


@needs_sandbox
def test_calibration_names_an_oracle_failing_for_some_other_reason(fixture_dir):
    (fixture_dir / "oracles" / "test_more.py").write_text("def test_calc_02():\n    raise KeyError('setup went wrong')\n")
    assert oracle_score.calibrate(fixture_dir, 60)["fails_for_another_reason"] == ["calc-02"]


@needs_sandbox
def test_calibration_names_a_serious_defect_with_no_oracle(fixture_dir):
    (fixture_dir / "oracles" / "NOT_TESTABLE.json").write_text("[]")
    assert oracle_score.calibrate(fixture_dir, 60)["no_oracle"] == ["calc-03"]


@needs_sandbox
def test_a_correct_fix_passes_its_oracle_and_breaks_nothing(fixture_dir, tmp_path):
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, FIX), set(), 60)
    assert record["applied"] and record["error"] is None
    assert record["oracles"]["calc-01"]["passed"] is True
    assert record["oracles_passed"] == 1
    assert record["original_tests"] == {"collected": 2, "failed": 0, "newly_failing": 0}
    assert record["root_causes"] == []


@needs_sandbox
def test_a_missing_fix_fails_the_oracle_with_its_reason(fixture_dir, tmp_path):
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, BREAK_DOUBLE), set(), 60)
    assert record["oracles"]["calc-01"]["passed"] is False
    assert "defect: add subtracts" in record["oracles"]["calc-01"]["reason"]


@needs_sandbox
def test_new_failures_with_one_cause_are_one_root_cause(fixture_dir, tmp_path):
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, BREAK_DOUBLE), set(), 60)
    assert record["root_cause_count"] == 1
    cause = record["root_causes"][0]
    assert (cause["exception"], cause["frame"]) == ("ValueError", "calc.py:double")
    assert len(cause["tests"]) == 2


@needs_sandbox
def test_the_original_tests_run_even_when_the_attempt_edited_them(fixture_dir, tmp_path):
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, HIDE_THE_BREAK), set(), 60)
    assert record["original_tests"]["newly_failing"] == 2


@needs_sandbox
def test_a_test_already_failing_at_the_start_does_not_count(fixture_dir, tmp_path):
    (fixture_dir / "repo" / "tests" / "test_old.py").write_text("def test_already_broken():\n    assert False\n")
    start = oracle_score.run_on_start(fixture_dir, "tests", 60)["cases"]
    baseline = {name for name, case in start.items() if case["outcome"] == "failed"}
    assert [name.split("::")[1] for name in baseline] == ["test_already_broken"]
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, FIX), baseline, 60)
    assert record["original_tests"]["failed"] == 1
    assert record["original_tests"]["newly_failing"] == 0


@needs_sandbox
def test_a_diff_that_does_not_apply_is_an_error_not_a_zero(fixture_dir, tmp_path):
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, DOES_NOT_APPLY), set(), 60)
    assert record["applied"] is False
    assert "git apply failed" in record["error"]
    assert "oracles_passed" not in record and "oracles" not in record


@needs_sandbox
def test_a_hanging_attempt_times_out_and_reports_an_error(fixture_dir, tmp_path):
    (fixture_dir / "oracles" / "test_more.py").write_text("import time\n\n\ndef test_calc_02():\n    time.sleep(60)\n")
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, FIX), set(), 1)
    assert "timed out" in record["error"]
    assert "oracles_passed" not in record


@needs_sandbox
def test_attempt_code_cannot_write_outside_its_scratch_copy(fixture_dir, tmp_path):
    target = tmp_path / "outside.txt"
    (fixture_dir / "oracles" / "test_more.py").write_text(f"""
def test_calc_02():
    with open({str(target)!r}, "w") as handle:
        handle.write("escaped")
""")
    record = oracle_score.score_diff(fixture_dir, write_diff(tmp_path, FIX), set(), 60)
    assert record["oracles"]["calc-02"]["passed"] is False
    assert not target.exists()


@needs_sandbox
def test_every_command_it_starts_goes_through_the_sandbox(fixture_dir, tmp_path, monkeypatch):
    commands, real = [], subprocess.Popen

    def spy(command, *args, **kwargs):
        commands.append(command)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    oracle_score.score_diff(fixture_dir, write_diff(tmp_path, FIX), set(), 60)
    assert len(commands) == 3  # git apply, the oracles, the original tests
    assert all(command[0] == "sandbox-exec" for command in commands)


def test_it_refuses_to_run_anything_without_a_sandbox(fixture_dir, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("started a process with no sandbox")

    monkeypatch.setattr(oracle_score.grade.shutil, "which", lambda name: None)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(SystemExit, match="sandbox-exec not found"):
        oracle_score.score_diff(fixture_dir, write_diff(tmp_path, FIX), set(), 60)
    with pytest.raises(SystemExit, match="sandbox-exec not found"):
        oracle_score.calibrate(fixture_dir, 60)


@needs_sandbox
def test_nothing_is_written_inside_the_fixture_and_results_go_to_out(fixture_dir, tmp_path, monkeypatch):
    before = tree(fixture_dir)
    good, bad = write_diff(tmp_path, FIX, "good"), write_diff(tmp_path, DOES_NOT_APPLY, "bad")
    out = tmp_path / "results"
    monkeypatch.setattr(sys, "argv", ["oracle_score.py", str(fixture_dir), str(good), str(bad), "--out", str(out)])
    assert oracle_score.main() == 1  # one diff did not apply
    assert tree(fixture_dir) == before
    assert json.loads((out / "good.json").read_text())["oracles_passed"] == 1
    assert json.loads((out / "bad.json").read_text())["applied"] is False


@needs_sandbox
def test_results_default_to_the_fixture_name_without_blind(fixture_dir, tmp_path, monkeypatch):
    blind = fixture_dir.rename(fixture_dir.with_name("blind-tiny"))
    monkeypatch.setattr(oracle_score, "EVALS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["oracle_score.py", "blind-tiny", "--calibrate"])
    assert oracle_score.main() == 0
    assert json.loads((tmp_path / "results" / "tiny" / "oracles" / "calibration.json").read_text())["oracles"] == 1
    assert blind.is_dir()


@pytest.mark.parametrize("name, expected", [("test_core_01", "core-01"), ("test_messaging_reports_06", "messaging_reports-06")])
def test_defect_id_from_test_name(name, expected):
    assert oracle_score.defect_id(name) == expected


def native_traceback(*frames, last="ValueError: no"):
    body = "".join(f'  File "{path}", line 3, in {name}\n    code()\n' for path, name in frames)
    return f"Traceback (most recent call last):\n{body}{last}\n"


def test_failure_cause_prefers_the_innermost_frame_in_the_code_under_test():
    text = native_traceback(("/ws/tests/test_a.py", "test_a"), ("/ws/pkg/mod.py", "outer"), ("/ws/pkg/mod.py", "inner"),
                            ("/ws/tests/helper.py", "callback"), ("/usr/lib/python3/json.py", "loads"))
    assert oracle_score.failure_cause(text, Path("/ws")) == ("ValueError", "pkg/mod.py:inner")


def test_failure_cause_falls_back_to_the_test_for_a_plain_assert():
    text = native_traceback(("/ws/tests/test_a.py", "test_a"), last="AssertionError: assert 200 == 404")
    assert oracle_score.failure_cause(text, Path("/ws")) == ("AssertionError", "tests/test_a.py:test_a")


def test_failure_cause_reads_the_last_traceback_of_a_chain_and_a_dotted_exception():
    first = native_traceback(("/ws/pkg/a.py", "first"), last="KeyError: 'x'")
    second = native_traceback(("/ws/pkg/b.py", "second"), last="vetdesk.core.errors.Conflict: taken")
    text = first + "\nDuring handling of the above exception, another exception occurred:\n\n" + second
    assert oracle_score.failure_cause(text, Path("/ws")) == ("Conflict", "pkg/b.py:second")


def test_root_causes_group_by_exception_and_frame():
    same = native_traceback(("/ws/pkg/a.py", "boom"))
    other_type = native_traceback(("/ws/pkg/a.py", "boom"), last="KeyError: 'x'")
    groups = oracle_score.root_causes({"t1": (same, ""), "t2": (same, ""), "t3": (other_type, "")}, Path("/ws"))
    assert [(g["exception"], g["frame"], g["tests"]) for g in groups] == [
        ("KeyError", "pkg/a.py:boom", ["t3"]), ("ValueError", "pkg/a.py:boom", ["t1", "t2"])]


def test_a_crash_a_route_turned_into_a_500_is_found_in_the_captured_log():
    assertion = native_traceback(("/ws/tests/test_a.py", "test_a"), last="AssertionError: assert 500 == 200")
    log = "ERROR vetdesk.core.http:http.py:247 unhandled\n" + native_traceback(
        ("/ws/pkg/http.py", "handle"), ("/ws/pkg/mod.py", "crash"), last="AttributeError: no attribute")
    assert oracle_score.failure_cause(assertion, Path("/ws"), log) == ("AttributeError", "pkg/mod.py:crash")


def test_a_failure_in_the_code_under_test_ignores_an_earlier_logged_crash():
    direct = native_traceback(("/ws/tests/test_a.py", "test_a"), ("/ws/pkg/mod.py", "direct"))
    log = native_traceback(("/ws/pkg/other.py", "earlier"), last="KeyError: 'x'")
    assert oracle_score.failure_cause(direct, Path("/ws"), log) == ("ValueError", "pkg/mod.py:direct")


def test_failed_asserts_in_one_test_module_are_one_root_cause():
    def failure(test):
        return (f'Traceback (most recent call last):\n  File "/ws/tests/a/test_a.py", line 3, in {test}\n    assert False\nAssertionError: no\n', "")
    source = ('Traceback (most recent call last):\n  File "/ws/app/fees.py", line 3, in refund\n    raise KeyError(1)\nKeyError: 1\n', "")
    causes = oracle_score.root_causes({"one": failure("test_one"), "two": failure("test_two"), "three": source}, Path("/ws"))
    assert sorted((cause["frame"], len(cause["tests"])) for cause in causes) == [("app/fees.py:refund", 1), ("tests/a/test_a.py", 2)]

