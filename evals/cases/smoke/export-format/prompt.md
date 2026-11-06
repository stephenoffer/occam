---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Please add a `markdown` export format to ledgerkit, so `python -m ledgerkit export ledger.json --format markdown` prints a GitHub-flavored markdown table with the columns Reference, Customer, Currency, Total.

- Reference is the same slug that `python -m ledgerkit link <reference>` gives.
- Total is the same amount the CSV export shows.
- It should be a first-class format: anywhere csv and json work, it works, with the same options. Documented, and importable from the package the same way the others are.

Also, money.py has two rounding helpers that look like copy-paste. Tidy that up while you're in there if it makes sense.
