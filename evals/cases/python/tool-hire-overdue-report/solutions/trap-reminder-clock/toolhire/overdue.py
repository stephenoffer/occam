"""The chase list: open hires that would be charged a late fee if they came back on a given day.

How late a hire is, what that costs and what deposit is held are the desk's business, so they are
passed in. That keeps this module free of imports from the desk, which needs to import it.
"""

COLUMNS = ("rental", "customer", "asset", "days_late", "late_fee", "deposit_held")


def overdue_rows(rentals, days_late, fee, deposit_held, money_str):
    """One row per chargeable hire, most days late first, then by rental id."""
    rows = []
    for rental in rentals:
        if rental.status != "open":
            continue
        days = days_late(rental)
        if days <= 0:
            continue
        rows.append(
            {
                "rental": rental.id,
                "customer": rental.customer,
                "asset": rental.asset,
                "days_late": days,
                "late_fee": money_str(fee(rental)),
                "deposit_held": money_str(deposit_held(rental)),
            }
        )
    rows.sort(key=lambda row: (-row["days_late"], row["rental"]))
    return rows
