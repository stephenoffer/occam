# ledgerkit

Small command-line tools for working with ledger exports.

    python -m ledgerkit export ledger.json --format csv
    python -m ledgerkit summary ledger.json
    python -m ledgerkit link "Invoice 12"
    python -m ledgerkit --list-formats

## Export formats

| Format | Description |
|--------|-------------|
| `csv`  | Comma-separated, one row per entry |
| `json` | JSON array of entries |
| `markdown` | GitHub-flavored markdown table |

Options: `--currency CUR` keeps only entries in that currency, `--summary-row` appends a total row.

## Rounding

Invoice totals round half up, as our invoicing contracts require. Dashboard summaries round half
even, to match the finance team's reporting.

Run the tests with `pytest`.
