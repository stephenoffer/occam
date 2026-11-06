# tidewater

Commercial and operations back office for a liner shipping group. Prices freight, raises invoices, settles carriers, files customs declarations, assesses claims and closes the ledger, alongside the operational desks (fleet, crew, ports and so on).

    python -m tidewater <command> <document.json>
    python -m tidewater batch <documents.json>

Each command reads one JSON document and prints a JSON result with a `total`. `batch` takes a list of `{"kind": <command>, "doc": {...}}` and prints a list of results, all in one process, which is how the overnight run works. See `examples/`.

## Documents

| Command | Document | Business date field |
|---|---|---|
| `quote` | Freight quote | `booked_on` |
| `invoice` | Invoice | `issued_on` (`due_on` is only the payment date) |
| `settlement` | Carrier settlement | `settled_on` |
| `declaration` | Customs declaration | `filed_on` |
| `claim` | Claim assessment | `assessed_on` (`incident_on` is informational) |
| `closing` | Period-end revaluation | `period_end` |
| `berth-charge` | Berth charge estimate | none |

## Layout

    tidewater/entrypoints   command line
    tidewater/services      one module per document type, plus the desks and digests
    tidewater/domain        rules and calculations, one package per business area
    tidewater/core          money, dates, exchange rates, shared helpers

More in `docs/`: `architecture.md`, `adjustments.md`, `glossary.md` and one page per domain under `domains/`.

Working on it: see `CONTRIBUTING.md`.
