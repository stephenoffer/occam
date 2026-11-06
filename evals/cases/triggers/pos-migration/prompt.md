---
tags: [triggers, positive, train]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

We need tenant_id on the sessions table with a backfill from users, without downtime. db/schema.sql has the current shape. Can you put the migration together?
