#!/usr/bin/env bash
set -eu
patch -s -p0 <<'PATCH'
--- toolhire/desk.py
+++ toolhire/desk.py
@@ -1710,10 +1710,17 @@
 }
 
 
-def main(argv: list[str] | None = None) -> int:
-    args = build_parser().parse_args(argv)
+def main(argv: list[str] | None = None, extra_commands=()) -> int:
+    """Run the desk. Each extra command is a pair of (add_to_parser, handlers to merge in)."""
+    parser = build_parser()
+    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
+    handlers = dict(HANDLERS)
+    for add_to_parser, more in extra_commands:
+        add_to_parser(subparsers)
+        handlers.update(more)
+    args = parser.parse_args(argv)
     try:
-        return HANDLERS[args.command](args)
+        return handlers[args.command](args)
     except HireError as exc:
         print(f"error: {exc}", file=sys.stderr)
         return 1
PATCH
patch -s -p0 <<'PATCH'
--- toolhire/__main__.py
+++ toolhire/__main__.py
@@ -1,10 +1,11 @@
 import sys
 
+from .chase_list import COMMAND
 from .desk import main
 
 
 def run() -> None:
-    sys.exit(main())
+    sys.exit(main(extra_commands=[COMMAND]))
 
 
 if __name__ == "__main__":
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
