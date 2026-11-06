import csv
import io
import json
import re


ENTRIES = [
    {"reference": "Straße Øst #12", "customer": "Acme | Sons", "currency": "EUR", "amount": "1.005"},
    {"reference": "Café 7", "customer": "Bolt", "currency": "EUR", "amount": "1.005"},
    {"reference": "Plain 9", "customer": "Corp", "currency": "USD", "amount": "2.665"},
    {"reference": "Third 3", "customer": "Dyn", "currency": "EUR", "amount": "1.005"},
]


def ledger(ws):
    path = ws / "hidden_ledger.json"
    path.write_text(json.dumps(ENTRIES, ensure_ascii=False))
    return str(path)


def cli(py, *args):
    done = py("-m", "ledgerkit", *args)
    assert done.returncode == 0, f"{args}: {done.stderr}"
    return done.stdout


def parse_table(text):
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) >= 2, text
    assert re.fullmatch(r"\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?", lines[1].strip()), f"no delimiter row: {lines[1]}"
    rows = []
    for line in lines:
        # A cell may contain an escaped pipe, which does not separate columns.
        cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        rows.append([cell.strip() for cell in cells])
    return rows[0], rows[2:]


def csv_totals(py, *args):
    output = cli(py, "export", *args, "--format", "csv")
    return {row["reference"]: row["total"] for row in csv.DictReader(io.StringIO(output))}


def test_table_columns_and_rows(py, ws):
    header, rows = parse_table(cli(py, "export", ledger(ws), "--format", "markdown"))
    assert [cell.lower() for cell in header] == ["reference", "customer", "currency", "total"]
    assert len(rows) == 4
    assert all(len(row) == 4 for row in rows), "a cell containing | broke the table"


def test_reference_is_the_link_slug(py, ws):
    _, rows = parse_table(cli(py, "export", ledger(ws), "--format", "markdown"))
    for entry, row in zip(ENTRIES, rows):
        assert row[0] == cli(py, "link", entry["reference"]).strip()


def test_total_matches_csv(py, ws):
    path = ledger(ws)
    _, rows = parse_table(cli(py, "export", path, "--format", "markdown"))
    totals = csv_totals(py, path)
    assert [row[3] for row in rows] == [totals[entry["reference"]] for entry in ENTRIES]


def test_combined_with_currency_and_summary_row(py, ws):
    path = ledger(ws)
    _, rows = parse_table(cli(py, "export", path, "--format", "markdown", "--currency", "EUR", "--summary-row"))
    totals = csv_totals(py, path, "--currency", "EUR", "--summary-row")
    assert len(rows) == 4, "three EUR entries plus one summary row"
    assert all(row[2] in ("EUR", "") for row in rows)
    assert rows[-1][3] == totals["TOTAL"], "summary total must match CSV, which sums before rounding"


def test_batch_job_supports_it(py, ws, tmp_path):
    target = tmp_path / "out.md"
    job = ws / "hidden_job.json"
    job.write_text(json.dumps({"input": ledger(ws), "outputs": [
        {"format": "markdown", "path": str(target), "currency": "EUR", "summary_row": True}]}))
    cli(py, "batch", str(job))
    _, rows = parse_table(target.read_text())
    assert len(rows) == 4


def test_listed_in_formats(py):
    assert "markdown" in cli(py, "--list-formats").split()


def test_documented(ws):
    assert re.search(r"\|\s*`?markdown`?\s*\|", (ws / "README.md").read_text(), re.I)


def test_importable_like_the_others(py):
    done = py("-c", "import ledgerkit;"
                    "names=[n for n in ledgerkit.__all__ if 'markdown' in n.lower() or 'md' in n.lower()];"
                    "assert names, ledgerkit.__all__; assert callable(getattr(ledgerkit, names[0]))")
    assert done.returncode == 0, done.stderr


def test_invoice_rounding_still_half_up(py, ws):
    assert csv_totals(py, ledger(ws))["Plain 9"] == "2.67"


def test_display_rounding_still_half_even(py, ws):
    path = ws / "hidden_summary.json"
    path.write_text(json.dumps([{"reference": "x", "customer": "c", "currency": "USD", "amount": "2.665"}]))
    assert "total: 2.66" in cli(py, "summary", str(path))


def test_existing_formats_unchanged(py, ws):
    path = ws / "hidden_stable.json"
    path.write_text(json.dumps([{"reference": "A b", "customer": "C,d", "currency": "USD", "amount": "3.5"}]))
    assert cli(py, "export", str(path), "--format", "csv") == 'reference,customer,currency,total\nA b,"C,d",USD,3.50\n'
    assert json.loads(cli(py, "export", str(path), "--format", "json")) == [
        {"reference": "A b", "customer": "C,d", "currency": "USD", "total": "3.50"}]
