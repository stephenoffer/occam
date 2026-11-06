#!/usr/bin/env bash
set -eu
patch -s -p0 <<'PATCH'
--- toolhire/desk.py
+++ toolhire/desk.py
@@ -1492,6 +1492,10 @@
 
     deposits = command("deposits", "deposits held against hires that are still out")
     _add_format(deposits)
+
+    overdue = command("overdue", "open hires that would be charged a late fee")
+    _add_as_of(overdue)
+    _add_format(overdue)
 
     revenue = command("revenue", "invoiced income by category")
     revenue.add_argument("--from", dest="start", required=True)
@@ -1629,6 +1633,32 @@
     return 0
 
 
+def overdue_rows(state: ShopState, on: dt.date) -> list[dict]:
+    """Open hires that would be charged a late fee if they came back on a given day."""
+    rows = []
+    for rental in state.rentals.values():
+        days = billable_late_days(state, rental, on) if rental.status == "open" else 0
+        if days:
+            rows.append(
+                {
+                    "rental": rental.id,
+                    "customer": rental.customer,
+                    "asset": rental.asset,
+                    "days_late": days,
+                    "late_fee": money_str(late_fee(state, rental, on)),
+                    "deposit_held": money_str(held_deposit(rental)),
+                }
+            )
+    return sorted(rows, key=lambda row: (-row["days_late"], row["rental"]))
+
+
+def _cmd_overdue(args: argparse.Namespace) -> int:
+    state = load_state(args.state)
+    columns = ("rental", "customer", "asset", "days_late", "late_fee", "deposit_held")
+    print(render_rows(overdue_rows(state, _report_day(args)), columns, args.format))
+    return 0
+
+
 def _cmd_revenue(args: argparse.Namespace) -> int:
     state = load_state(args.state)
     rows = revenue_rows(state, parse_date(args.start), parse_date(args.end))
@@ -1699,6 +1729,7 @@
     "reminders": _cmd_reminders,
     "utilization": _cmd_utilization,
     "deposits": _cmd_deposits,
+    "overdue": _cmd_overdue,
     "revenue": _cmd_revenue,
     "service-due": _cmd_service_due,
     "customers": _cmd_customers,
PATCH
patch -s -p0 <<'PATCH'
--- README.md
+++ README.md
@@ -16,6 +16,7 @@
 | `reminders` | Hires due a reminder letter, or the letters with `--letters` |
 | `utilization` | Share of each category's time spent out on hire |
 | `deposits` | Deposits held against hires that are still out |
+| `overdue` | Open hires that would be charged a late fee on a given day |
 | `revenue` | Invoiced income by category over a period |
 | `service-due` | Assets that need servicing |
 | `customers` | Each customer's outstanding balance and standing |
PATCH
