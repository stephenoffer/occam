# Brindle Hardware store systems

The software behind the tills in Brindle Hardware's six stores, and the head office tools that
turn each store's day into numbers for finance.

## Packages

| Package | What it does | Runs on |
|---|---|---|
| `catalog` | The product catalogue: SKUs, prices, departments. Weekly refresh and price-change files. | store PC |
| `till` | Rings sales from the till front end, prints receipts, keeps the day's sales journal, does the end-of-day cash-up and closes the day. | till |
| `stock` | Stock on hand per store: takes each day's sales off stock, books deliveries in. | store PC |
| `backoffice` | Head office: store takings from the tapes stores upload, and postings for the accounts package. See [backoffice/README.md](backoffice/README.md). | finance server |

## Running things

    python -m till --data var/till ring data/baskets/paint-and-fixings.json
    python -m till --data var/till cashup --date 2026-11-09 --counted-cash 152.38
    python -m till --data var/till close --date 2026-11-09
    python -m stock --data var/till deplete --date 2026-11-09
    python -m backoffice takings --inbox var/inbox --date 2026-11-09

`--data` is the till's data directory. On a real till it's `/srv/till`; anything works for testing.
Its `till.ini` sets the store code, till number and float ([till/settings.py](till/settings.py)).

## Tests

    python -m pytest

There are no dependencies beyond Python 3.10 and pytest.

## Docs

- [docs/cashup.md](docs/cashup.md): how a manager cashes up and closes the day.
- [docs/adr](docs/adr): decisions we keep having to explain.
- [CONTRIBUTING.md](CONTRIBUTING.md): how we work.
