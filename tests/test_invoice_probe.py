"""The invoice probe decides a preregistered criterion, so a wrong "right" or a wrong "wrong" would misreport the money catch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import invoice_probe

STARTER = invoice_probe.CASE / "files" / "sql" / "invoice_totals.sql"
SOLUTIONS = invoice_probe.CASE / "solutions"

# Right without the huge line, and the way the saved Sonnet runs go wrong with it: the price overflows to REAL,
# the sum turns REAL, and text formatting meant for an integer splits "3998.0".
OVERFLOWS = """
SELECT i.id AS invoice_id, i.currency AS currency,
       CASE WHEN c.minor_digits = 0 THEN CAST(t.m AS TEXT)
            ELSE substr(CAST(t.m AS TEXT), 1, length(CAST(t.m AS TEXT)) - c.minor_digits) || '.' || substr(CAST(t.m AS TEXT), -c.minor_digits)
       END AS total
FROM invoices AS i
JOIN currencies AS c ON c.code = i.currency
JOIN (SELECT invoice_id, SUM(CAST(replace(unit_price, '.', '') AS INTEGER) * 1000000 * quantity * (10000 + tax_bp) / 10000) / 1000000 AS m
      FROM invoice_lines GROUP BY invoice_id) AS t ON t.invoice_id = i.id
ORDER BY i.id
"""


def diff(tmp_path: Path, old: str, new: str) -> str:
    """The patch the grader would save for a run that changed only the query, in its `diff -ruN` form."""
    for side, text in (("a", old), ("b", new)):
        (tmp_path / side / "sql").mkdir(parents=True)
        (tmp_path / side / "sql" / "invoice_totals.sql").write_text(text)
    made = subprocess.run(["diff", "-ruN", "a", "b"], cwd=tmp_path, capture_output=True, text=True)
    assert made.returncode in (0, 1), made.stderr
    return made.stdout


def saved_run(tmp_path: Path, sql: str, patch: str | None = None) -> Path:
    run = tmp_path / "with-0"
    run.mkdir()
    (run / "diff.patch").write_text(diff(tmp_path, STARTER.read_text(), sql) if patch is None else patch)
    return run


def test_the_reference_solution_is_right(tmp_path):
    assert invoice_probe.probe(saved_run(tmp_path, (SOLUTIONS / "reference" / "sql" / "invoice_totals.sql").read_text())) == "right"


def test_a_query_the_huge_line_corrupts_is_wrong(tmp_path):
    verdict = invoice_probe.probe(saved_run(tmp_path, OVERFLOWS))
    assert verdict.startswith("wrong") and "gave '3998..0', rules give '39.98'" in verdict


def test_a_query_wrong_without_the_line_is_not_counted(tmp_path):
    """The starter query formats JPY as 1650.00, which has nothing to do with the huge line."""
    assert invoice_probe.probe(saved_run(tmp_path, STARTER.read_text())).startswith("not probed: wrong without the huge line")


def test_a_number_where_the_suite_wants_text_is_not_right(tmp_path):
    """Right in value for both currencies, and text for JPY, so only the type separates it from a right answer."""
    numbers = "SELECT 1, i.currency, CASE WHEN i.currency = 'USD' THEN 39.98 ELSE '1650' END FROM invoices AS i"
    verdict = invoice_probe.probe(saved_run(tmp_path, numbers))
    assert verdict.startswith("not probed") and "USD" in verdict and "gave 39.98," in verdict and "JPY" not in verdict


def test_a_query_that_fails_is_not_right(tmp_path):
    assert "error: OperationalError" in invoice_probe.probe(saved_run(tmp_path, "SELECT * FROM no_such_table"))


def test_a_query_that_hangs_stops_at_the_suites_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_probe.rules, "QUERY_SECONDS", 0.2)
    endless = "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT 1, 'USD', count(*) FROM r"
    assert "error: OperationalError" in invoice_probe.probe(saved_run(tmp_path, endless))


def test_a_patch_that_does_not_apply_is_not_probed(tmp_path):
    broken = "--- a/sql/invoice_totals.sql\n+++ b/sql/invoice_totals.sql\n@@ -1,1 +1,1 @@\n-no such line\n+x\n"
    assert invoice_probe.probe(saved_run(tmp_path, "", patch=broken)).startswith("not probed: patch failed")


def test_a_reversed_patch_is_not_applied_backwards(tmp_path):
    reference = (SOLUTIONS / "reference" / "sql" / "invoice_totals.sql").read_text()
    backwards = diff(tmp_path / "made", reference, STARTER.read_text())
    assert invoice_probe.probe(saved_run(tmp_path, "", patch=backwards)).startswith("not probed")


def test_a_label_without_grading_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(invoice_probe, "EVALS", tmp_path)
    monkeypatch.setattr("sys.argv", ["invoice_probe.py", "ungraded"])
    assert invoice_probe.main() == 0
    assert capsys.readouterr().out == "ungraded: no graded.json\n"


def test_every_graded_run_gets_a_line_with_its_acceptance(tmp_path, monkeypatch, capsys):
    graded = tmp_path / "results" / "label" / "graded"
    graded.mkdir(parents=True)
    records = [{"case": "invoice-ledger-totals", "arm": "with", "run": 0, "acceptance": False},
               {"case": "other-case", "arm": "with", "run": 0, "acceptance": True}]
    (graded / "graded.json").write_text(json.dumps(records))
    monkeypatch.setattr(invoice_probe, "EVALS", tmp_path)
    monkeypatch.setattr("sys.argv", ["invoice_probe.py", "label"])
    assert invoice_probe.main() == 0
    assert capsys.readouterr().out.split() == ["label", "with-0", "acceptance", "failed", "not", "probed:", "no", "saved", "workspace"]
