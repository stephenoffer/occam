def top_customers(rows, n=3):
    names = []
    for row in rows:
        if row["customer"] not in names:
            names.append(row["customer"])
    totals = []
    for name in names:
        totals.append((sum(r["amount"] for r in rows if r["customer"] == name), name))
    return [name for _, name in sorted(totals, key=lambda t: (-t[0], t[1]))[:n]]
