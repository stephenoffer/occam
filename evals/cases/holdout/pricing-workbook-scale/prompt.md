---
tags: [holdout]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`python -m pricemodel models/sample.json` works fine, but it falls over or never finishes on the model finance just exported. That one has about 60k cells: carry-forward chains where each period builds on the one before (the longest is about 30k cells), layers of subtotals that build on the same earlier subtotals, and rollups over tens of thousands of line items where each subtotal adds up about ten cells.

Two things have to hold on a model that size:

1. Loading it with `Workbook.set`, with the cells arriving in any order, and then reading every cell has to take under 10 seconds. Same for the CLI.
2. We're putting `Workbook` behind a what-if tool, where someone edits a cell with `set` and reads a total with `get`, thousands of times in a session. That round trip has to average under 5 ms, and every `get` has to reflect all the edits so far. A cell can be given a new formula at any point, not just a new number.

A circular reference still has to surface as `CircularReference` instead of hanging or crashing, however long the loop is, and the workbook has to work normally again once the loop is edited away.

Keep the `Workbook` API and the CLI as they are. Standard library only.
