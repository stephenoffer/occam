---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

The stock report prints `1 items` when a count is one, e.g. `python -m stockreport data/sample.csv` shows `WIDGET: 1 items`. It should say `1 item`. Can you fix that?
