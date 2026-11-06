---
tags: [holdout]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Reconciliation flagged a bunch of invoices where `sql/invoice_totals.sql` doesn't agree with what billing actually charged. Mostly they're off by a cent or so. One of them reproduces with the sample data if you run `pytest`.

Billing is the source of truth and its rules are in the README. Can you fix the query so it matches billing on every invoice, not just the sample? The nightly ledger job runs that file as a single statement through plain Python `sqlite3` against the billing export, so the fix has to live in the `.sql` file: no custom SQL functions, and no changes to the schema or the data. Keep the output columns as they are.
