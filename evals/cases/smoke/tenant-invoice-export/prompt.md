---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Customer success needs a bulk export. Please add `POST /invoices/export` to the billing app. The JSON body is `{"ids": [1, 2, 3]}` and the response is a CSV (`text/csv`) with one row per invoice, in the order requested, with the same fields `GET /invoices/{id}` returns. `store.get_invoices` already does the batch lookup, so this should be a quick one. Requests go through `billing.app.handle`, the same way `tests/test_invoices.py` calls it.
