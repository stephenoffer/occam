# toolhire

Back office for a tool hire business: the catalog, rentals, return settlement, overdue notices and monthly reporting.

    python -m toolhire settle --rental rental.json --returned-on 2026-03-09 [--damage-cents 2000]

`rental.json` holds the rental's fields, as in `toolhire/models.py`. Settling prints what was charged and released as JSON.

Late fee policy is in `docs/late-fee-policy.md`.

## Tests

    python -m pytest
