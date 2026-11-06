# invoice-ledger

The nightly ledger job totals invoices from the billing export.

    python report.py path/to/export.sqlite3    # prints invoice_id,currency,total as CSV

`sql/invoice_totals.sql` is the query the job runs. It is one statement, executed
with `connection.execute(text)`. `sql/schema.sql` is the export's schema, which billing
owns. `data/sample_seed.sql` is a small sample, and `data/billing_totals.csv` holds the
totals billing charged for it.

Run the tests with `pytest`.

## Export data

- `currencies.minor_digits` is the number of decimal digits in the currency's minor
  unit: 2 for USD, 0 for JPY, 3 for KWD.
- `invoice_lines.unit_price` is a decimal string in major units. It is never negative.
  It has at most 6 decimal places, and may have none: `19.99`, `1500`, `10.5`, `0.0125`.
- `invoice_lines.quantity` is a whole number. Credit lines have a negative quantity.
- `discount_bp` and `tax_bp` are in basis points, from 0 to 10000. 825 means 8.25%.
- Before discount, a line is never more than one million major units in either direction.

## Billing rules

For each line, in this order:

1. `net = unit_price * quantity * (1 - discount)`, rounded to the currency's minor unit.
2. `tax = net * tax rate`, using the rounded net, rounded to the currency's minor unit.
3. The line's total is `net + tax`.

Rounding is to the nearest minor unit, and an exact half rounds away from zero: 1.005
USD becomes 1.01 and -1.005 USD becomes -1.01.

An invoice's total is the sum of its line totals.

## Query output

One row per invoice that has at least one line, ordered by invoice id:

| column       | meaning                                                                |
|--------------|------------------------------------------------------------------------|
| `invoice_id` | the invoice's id                                                       |
| `currency`   | the invoice's currency code                                            |
| `total`      | text, with exactly the currency's minor digits: `43.28`, `1500`, `1.235`, `-18.00` |
