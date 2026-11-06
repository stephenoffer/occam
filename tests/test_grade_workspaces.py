"""The grader must not leave agent-written code running behind it."""

import subprocess
import time

import grade_workspaces as grade

MARKER = "31337.0"


def stray_processes():
    done = subprocess.run(["pgrep", "-f", f"sleep {MARKER}"], capture_output=True, text=True)
    return done.stdout.split()


def make_case(tmp_path, body):
    case = tmp_path / "case"
    (case / "hidden").mkdir(parents=True)
    (case / "hidden" / "test_it.py").write_text(body)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return case, workspace


def test_a_child_left_running_by_a_check_does_not_outlive_grading(tmp_path):
    case, workspace = make_case(tmp_path, f"""
import subprocess


def test_starts_a_child_and_abandons_it():
    subprocess.Popen(["sleep", "{MARKER}"])
""")
    result = grade.run_hidden(case, workspace)
    assert result["passed"], result["output"]
    time.sleep(0.2)
    assert stray_processes() == []


def test_timeout_also_kills_children(tmp_path):
    case, workspace = make_case(tmp_path, f"""
import subprocess


def test_hangs():
    subprocess.run(["sleep", "{MARKER}"])
""")
    result = grade.run_hidden(case, workspace, timeout=3)
    assert not result["passed"]
    assert result["failed"] == ["<grader timeout>"]
    time.sleep(0.2)
    assert stray_processes() == []


def test_changed_lines_reads_the_hunks_not_the_look_of_each_line():
    diff = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1,3 +1,3 @@\n--- a removed SQL comment\n+++ an added line that looks like a header\n"
            " select 1\n-select\f2\n+select 3\n\\ No newline at end of file\n"
            "diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -1 +1 @@\n-a\n+b\n")
    assert grade.changed_lines(diff) == 6


def test_changed_lines_counts_a_new_file():
    assert grade.changed_lines("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+a\n+b\n") == 2
