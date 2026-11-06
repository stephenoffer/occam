---
tags: [python]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

The counter staff want a chase list. Please add an `overdue` report to toolhire, so `python -m toolhire overdue shop.json --as-of 2026-03-16` lists every open hire that would be charged a late fee if it came back that day, most days late first, then by rental id.

Columns are `rental`, `customer`, `asset`, `days_late`, `late_fee`, `deposit_held`. The days and the fee have to agree with what `return` would actually charge on that date, and the deposit with the `deposits` report. Leave out disputed hires, we don't chase those. `--format` should work the way it does on the other reports, and it should go in the README table with them.

Should be a quick one, it's basically the deposits report with a couple more columns.
