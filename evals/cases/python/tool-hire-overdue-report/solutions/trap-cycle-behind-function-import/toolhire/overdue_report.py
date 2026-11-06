"""The chase list report."""

from .desk import billable_late_days, held_deposit, late_fee, money_str

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
