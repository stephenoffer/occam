#!/usr/bin/env bash
set -eu
patch -s -p0 <<'PATCH'
--- toolhire/desk.py
+++ toolhire/desk.py
@@ -19,6 +19,9 @@
 from pathlib import Path
 from typing import Iterable, Iterator
 
+from .overdue import COLUMNS as OVERDUE_COLUMNS
+from .overdue import overdue_rows
+
 # ---------------------------------------------------------------------------
 # Errors
 # ---------------------------------------------------------------------------
@@ -1493,6 +1496,10 @@
     deposits = command("deposits", "deposits held against hires that are still out")
     _add_format(deposits)
 
+    overdue = command("overdue", "open hires that would be charged a late fee")
+    _add_as_of(overdue)
+    _add_format(overdue)
+
     revenue = command("revenue", "invoiced income by category")
     revenue.add_argument("--from", dest="start", required=True)
     revenue.add_argument("--to", dest="end", required=True)
@@ -1626,6 +1633,20 @@
 def _cmd_deposits(args: argparse.Namespace) -> int:
     state = load_state(args.state)
     print(render_rows(deposit_rows(state), ("rental", "customer", "asset", "deposit_held"), args.format))
+    return 0
+
+
+def _cmd_overdue(args: argparse.Namespace) -> int:
+    state = load_state(args.state)
+    on = _report_day(args)
+    rows = overdue_rows(
+        state.rentals.values(),
+        days_late=lambda rental: billable_late_days(state, rental, on),
+        fee=lambda rental: late_fee(state, rental, on),
+        deposit_held=held_deposit,
+        money_str=money_str,
+    )
+    print(render_rows(rows, OVERDUE_COLUMNS, args.format))
     return 0
 
 
@@ -1699,6 +1720,7 @@
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
python3 - <<'PY'
import re
from pathlib import Path
path = Path("toolhire/desk.py")
text = path.read_text()
banner = re.compile(r"^# -+\n# (.+)\n# -+\n", re.M)
marks = list(banner.finditer(text))
head = text[:marks[0].start()]
sections = {m.group(1): text[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(text))] for i, m in enumerate(marks)}
imports = head[head.index("from __future__"):]
Path("toolhire/primitives.py").write_text(imports + sections["Errors"] + sections["Money"] + sections["Calendar"])
Path("toolhire/records.py").write_text(imports + "from .primitives import *\n\n" + sections["Catalog"] + sections["Customers"])
rest = text
for name in ("Errors", "Money", "Calendar", "Catalog", "Customers"):
    rest = rest.replace(sections[name], "")
rest = rest.replace(imports, imports + "from .primitives import *\nfrom .records import *\n\n", 1)
path.write_text(rest)
PY
