# freightquote

Quoting engine for the ops desk. Given a shipment and a lane from the quarterly rate card, it
works out base freight, volume discount and surcharges, and produces a quote that is good for
seven days. Accepted quotes are booked with the carrier API (`https://api.carrier.invalid`).

## Usage

    python3 -m freightquote --card data/ratecard.json --fuel data/fuel_index.json \
        --lane HFX-MTL-ROAD --weight 120 --volume 1.2 --units 4

Add `--dg-class 3` for dangerous goods shipments and `--archive quotes.db` to keep a copy of the
quote in a local SQLite archive.

## How a quote is built

1. The lane's mode decides which eligibility rules apply (`eligibility.py`). A shipment that a
   lane can't carry doesn't get a quote.
2. Base freight is distance plus chargeable weight, with a per-mode minimum (`pricing.py`).
3. Orders of 10 units or more earn a volume discount.
4. Fuel, oversize, remote area and dangerous goods surcharges are added (`surcharges.py`).
   The dangerous goods rate comes from the published tariff tables, per class and per kg.

## Data files

- `data/ratecard.json` is published by the desk each quarter.
- `data/fuel_index.json` is the carriers' weekly fuel index.

## Checks

`scripts/check.sh` runs what CI runs: ruff, mypy and pytest.
