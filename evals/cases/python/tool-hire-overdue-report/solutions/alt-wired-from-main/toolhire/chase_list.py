"""The chase list report. It depends on the desk; nothing in the desk depends on it."""

import datetime as dt

from .desk import OUTPUT_FORMATS, billable_late_days, held_deposit, late_fee, load_state, money_str, parse_date, render_rows

COLUMNS = ("rental", "customer", "asset", "days_late", "late_fee", "deposit_held")


def overdue_rows(state, on):
    rows = []
    for rental in state.rentals.values():
        days = billable_late_days(state, rental, on) if rental.status == "open" else 0
        if days:
            rows.append(
                {
                    "rental": rental.id,
                    "customer": rental.customer,
                    "asset": rental.asset,
                    "days_late": days,
                    "late_fee": money_str(late_fee(state, rental, on)),
                    "deposit_held": money_str(held_deposit(rental)),
                }
            )
    return sorted(rows, key=lambda row: (-row["days_late"], row["rental"]))


def handle(args):
    state = load_state(args.state)
    on = parse_date(args.as_of) if args.as_of else dt.date.today()
    print(render_rows(overdue_rows(state, on), COLUMNS, args.format))
    return 0


def add_to_parser(subparsers):
    parser = subparsers.add_parser("overdue", help="open hires that would be charged a late fee")
    parser.add_argument("state")
    parser.add_argument("--as-of")
    parser.add_argument("--format", choices=OUTPUT_FORMATS, default="table")


COMMAND = (add_to_parser, {"overdue": handle})
