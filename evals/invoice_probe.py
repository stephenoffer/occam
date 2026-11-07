#!/usr/bin/env python3
"""Post-hoc probe on saved `invoice-ledger-totals` runs: does a quantity-0 line with a huge price corrupt the invoice total? Spends nothing.

    invoice_probe.py LABEL [LABEL ...]

Rebuilds each graded run's workspace from the case files and its saved `diff.patch`, then runs the agent's
`sql/invoice_totals.sql` on invoices with and without such a line, and compares the text it returns with the hidden
suite's own billing rules. "right" needs both, so a query that's wrong anyway doesn't count as surviving the line.
Hidden acceptance is printed beside each verdict. The input came from a plugin run's report, so this is a lead fixed
before the Opus cost run in `PREREGISTRATION.md`, not a graded check.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EVALS = Path(__file__).resolve().parent
CASE = EVALS / "cases" / "holdout" / "invoice-ledger-totals"
sys.path.insert(0, str(CASE / "hidden"))
import test_billing_rules as rules  # noqa: E402  the hidden suite's schema, rules and query time limit

NORMAL = {"USD": [("19.99", 2, 0, 0)], "JPY": [("1500", 1, 0, 1000)]}
HUGE = [("USD", ("99999999999999999999.99", 0, 0, 0)), ("USD", ("9223372036854775807", 0, 0, 0)),
        ("JPY", ("123456789012345678901234567890", 0, 0, 0))]


def total(query: str, currency: str, lines: list[tuple]) -> object:
    """The total column for one invoice, exactly as the query returns it, or why it gave none."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(rules.SCHEMA)
        connection.executemany("INSERT INTO currencies VALUES (?, ?)", rules.MINOR_DIGITS.items())
        connection.execute("INSERT INTO invoices VALUES (1, 'Customer', ?, '2026-09-01')", (currency,))
        connection.executemany("INSERT INTO invoice_lines (invoice_id, description, unit_price, quantity, discount_bp, tax_bp)"
                               " VALUES (1, 'Line', ?, ?, ?, ?)", lines)
        deadline = time.monotonic() + rules.QUERY_SECONDS
        connection.set_progress_handler(lambda: time.monotonic() > deadline, 100_000)
        return connection.execute(query).fetchall()[0][2]
    except Exception as error:  # a query that fails or hangs on this input gives a wrong answer, so record it rather than stop
        return f"error: {type(error).__name__}"
    finally:
        connection.close()


def misses(query: str, invoices: list[tuple[str, list[tuple]]]) -> list[str]:
    """Each invoice whose total isn't the rules' text, exactly: the hidden suite compares strings too."""
    found = []
    for currency, lines in invoices:
        got, want = total(query, currency, lines), rules.expected_total(currency, lines)
        if got != want:
            found.append(f"{currency} {lines[-1][0][:12]}: gave {got!r}, rules give {want!r}")
    return found


def probe(run: Path) -> str:
    with tempfile.TemporaryDirectory() as scratch:
        workspace = Path(scratch) / "ws"
        shutil.copytree(CASE / "files", workspace)
        try:  # forward only, no fuzz, never a prompt: the grader always diffs from these starting files
            applied = subprocess.run(["patch", "-p1", "-s", "-N", "-t", "-F", "0", "-i", str(run / "diff.patch")], cwd=workspace,
                                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return "not probed: patch timed out"
        if applied.returncode:
            return f"not probed: patch failed: {' '.join((applied.stdout + applied.stderr).split())[:120]}"
        sql = workspace / "sql" / "invoice_totals.sql"
        query = sql.read_text() if sql.exists() else ""
        if control := misses(query, list(NORMAL.items())):
            return "not probed: wrong without the huge line, " + "; ".join(control)
        huge = misses(query, [(currency, NORMAL[currency] + [line]) for currency, line in HUGE])
        return "right" if not huge else "wrong: " + "; ".join(huge)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2
    for label in sys.argv[1:]:
        graded = EVALS / "results" / label / "graded"
        try:
            records = [r for r in json.loads((graded / "graded.json").read_text()) if r["case"] == "invoice-ledger-totals"]
        except FileNotFoundError:
            print(f"{label}: no graded.json")
            continue
        for record in sorted(records, key=lambda r: (r["arm"], r["run"])):
            run = graded / "invoice-ledger-totals" / f"{record['arm']}-{record['run']}"
            verdict = probe(run) if (run / "diff.patch").exists() else "not probed: no saved workspace"
            accepted = {True: "passed", False: "failed"}.get(record.get("acceptance"), "unknown")
            print(f"{label:24} {run.name:10} acceptance {accepted:7} {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
