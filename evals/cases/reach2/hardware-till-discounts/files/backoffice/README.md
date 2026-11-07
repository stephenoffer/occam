# backoffice

Head office's side of the daily numbers. Every store uploads one tape per trading day; the upload
service drops them into the inbox, and from there:

- `python -m backoffice takings --inbox DIR --date D` shows each store's takings for the day: sales
  by department, cash banked, card, and anything that needs a look (sales whose lines don't match
  what was paid, records set aside as quarantined).
- `python -m backoffice postings --inbox DIR --date D` writes the CSV the accounts package imports.

Finance runs both each morning for the previous day, and again at month end for late tapes.

This package is deployed on the finance server on its own. It depends on nothing but the standard
library and must not import store-side packages: the tape format in
[docs/tape-format.md](docs/tape-format.md) is the whole interface (ADR 0002).

## Tests

    python -m pytest backoffice/tests

The fixture tapes in `tests/fixtures` are real tapes from October, with card references removed.
