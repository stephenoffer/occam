# toolhire

The front desk for a tool hire shop: pricing, bookings, check-out and return, reminders, servicing,
invoices and reports. A shop's records live in one JSON state file, which every command takes as its
first argument. `examples/shop.json` is a small made-up shop to try things on.

    python -m toolhire quote examples/shop.json --category DRILL --start 2026-03-02 --end 2026-03-09
    python -m toolhire checkout examples/shop.json C-1 DR-101 --start 2026-03-02 --due 2026-03-06
    python -m toolhire return examples/shop.json R-1 --on 2026-03-10 --dry-run
    python -m toolhire deposits examples/shop.json --format csv

## Reports

| Command | Shows |
|---------|-------|
| `reminders` | Hires due a reminder letter, or the letters with `--letters` |
| `utilization` | Share of each category's time spent out on hire |
| `deposits` | Deposits held against hires that are still out |
| `revenue` | Invoiced income by category over a period |
| `service-due` | Assets that need servicing |
| `customers` | Each customer's outstanding balance and standing |
| `fleet` | Replacement value and service cost of each category |

Reports take `--format table|csv|json`. Reports about a point in time take `--as-of YYYY-MM-DD`.

## Late returns

Return dates count open days only. Each category has grace days, and trade and contractor customers
get more. After that the fee is one and a half times the daily rate per day, up to the asset's
replacement value. An approved extension moves the due date.

Reminder letters run on a separate, simpler clock: see `reminders`.

Run the tests with `pytest`.
