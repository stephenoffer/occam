# shopfront

Storefront back office. `pytest` runs the tests.

## Prices

Amounts are integers in the currency's minor units. They're shown with the currency's symbol, the major units with no
thousands separator, and the minor units after a point, padded to the currency's digits. A currency with no minor
digits has no point.

| Currency | Symbol | Minor digits | 1250 shows as |
|---|---|---|---|
| USD | $ | 2 | $12.50 |
| EUR | € | 2 | €12.50 |
| GBP | £ | 2 | £12.50 |
| JPY | ¥ | 0 | ¥1250 |
