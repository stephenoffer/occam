"""The free code-size comparison: counts added lines correctly, and its accepted-only view really drops the others."""

import json

import code_size

PATCH = """diff -ruN a/app/core.py b/app/core.py
--- a/app/core.py\t2026-01-01
+++ b/app/core.py\t2026-01-02
@@ -1,2 +1,3 @@
 def f():
-    return 1
+    x = 2
+    return x
diff -ruN a/tests/test_core.py b/tests/test_core.py
--- a/tests/test_core.py\t2026-01-01
+++ b/tests/test_core.py\t2026-01-02
@@ -0,0 +1,1 @@
+assert f() == 2
diff -ruN a/README.md b/README.md
--- a/README.md\t2026-01-01
+++ b/README.md\t2026-01-02
@@ -0,0 +1,1 @@
+words
"""


def test_measure_separates_source_from_tests_and_ignores_prose():
    size = code_size.measure(PATCH)
    assert (size.source_added, size.test_added) == (2, 1)
    assert size.gzip_bytes > 0


def test_nothing_added_measures_zero():
    assert code_size.measure("") == code_size.Size(0, 0, 0)


def suite(tmp_path, records):
    """A results folder holding the runs described, each with a patch adding `lines` lines of source."""
    base = tmp_path / "suite" / "graded"
    rows = []
    for arm, run, lines, accepted, reason in records:
        folder = base / "case" / f"{arm}-{run}"
        folder.mkdir(parents=True)
        (folder / "diff.patch").write_text("--- a/a.py\n+++ b/a.py\n" + "".join(f"+x{i} = {i}\n" for i in range(lines)))
        rows.append({"case": "case", "arm": arm, "run": run, "acceptance": accepted, "error": None, "eval_cost_usd": 1.0, "metrics": {"terminal_reason": reason}})
    (base / "graded.json").write_text(json.dumps(rows))
    return tmp_path


def test_accepted_only_drops_failed_and_truncated_runs(tmp_path):
    results = suite(tmp_path, [("with", 0, 10, True, "success"), ("with", 1, 2, False, "success"), ("with", 2, 3, True, "max_turns"), ("without", 0, 20, True, "success")])
    runs = code_size.load_runs("suite", "with", results)
    assert [run["accepted"] for run in runs] == [True, False, False]
    kept = code_size.by_case(runs, accepted_only=True)["case"]
    assert [run["size"].source_added for run in kept] == [10]


def test_compare_reports_the_ratio_against_the_baseline(tmp_path):
    results = suite(tmp_path, [("with", 0, 10, True, "success"), ("without", 0, 20, True, "success")])
    text = "\n".join(code_size.compare("suite", code_size.load_runs("suite", "with", results), code_size.load_runs("suite", "without", results), False))
    assert "source lines 0.50" in text and "Smaller on 1, larger on 0" in text


def test_an_added_line_that_looks_like_a_header_is_counted():
    patch = "--- a/a.c\t1\n+++ b/a.c\t2\n@@ -0,0 +1,3 @@\n+int i = 0;\n++ i;\n+i += 1;\n"
    assert code_size.measure(patch).source_added == 3


def test_a_run_that_errored_is_not_accepted(tmp_path):
    results = suite(tmp_path, [("with", 0, 10, True, "success")])
    graded = results / "suite" / "graded" / "graded.json"
    rows = json.loads(graded.read_text())
    rows[0]["error"] = "timed out"
    rows[0]["metrics"] = {"terminal_reason": None}
    graded.write_text(json.dumps(rows))
    assert code_size.by_case(code_size.load_runs("suite", "with", results), accepted_only=True) == {}


def test_a_missing_cost_leaves_the_case_out_rather_than_crashing(tmp_path):
    results = suite(tmp_path, [("with", 0, 10, True, "success"), ("without", 0, 20, True, "success")])
    graded = results / "suite" / "graded" / "graded.json"
    rows = json.loads(graded.read_text())
    rows[1]["eval_cost_usd"] = None
    graded.write_text(json.dumps(rows))
    text = "\n".join(code_size.compare("suite", code_size.load_runs("suite", "with", results), code_size.load_runs("suite", "without", results), False))
    assert "Left out of that ratio" in text and "case" in text


def test_a_suite_with_no_baseline_says_so(tmp_path):
    results = suite(tmp_path, [("with", 0, 10, True, "success")])
    text = "\n".join(code_size.compare("suite", code_size.load_runs("suite", "with", results), [], False))
    assert "nothing compares" in text


def test_a_missing_suite_is_a_clear_error(capsys):
    assert code_size.main(["no-such-suite"]) == 2
    assert "no-such-suite" in capsys.readouterr().err
