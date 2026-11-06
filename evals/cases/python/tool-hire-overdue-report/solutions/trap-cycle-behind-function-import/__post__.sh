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
@@ -1629,6 +1633,14 @@
     return 0
 
 
+def _cmd_overdue(args: argparse.Namespace) -> int:
+    from .overdue_report import COLUMNS, overdue_rows  # here rather than at the top, to avoid a circular import
+
+    state = load_state(args.state)
+    print(render_rows(overdue_rows(state, _report_day(args)), COLUMNS, args.format))
+    return 0
+
+
 def _cmd_revenue(args: argparse.Namespace) -> int:
     state = load_state(args.state)
     rows = revenue_rows(state, parse_date(args.start), parse_date(args.end))
@@ -1699,6 +1711,7 @@
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
