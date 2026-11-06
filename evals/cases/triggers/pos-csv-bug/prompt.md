---
tags: [triggers, positive, train]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Users with a newline or comma in their name break the CSV from exporting/csv_writer.py, the rows come out shifted and finance can't open it. Please fix.
