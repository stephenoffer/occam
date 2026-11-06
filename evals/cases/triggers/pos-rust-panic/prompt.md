---
tags: [triggers, positive, train]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

orderparser panics on an empty line, first_field in parser/src/lib.rs, and it took down the ingest worker last night. fix it please
