---
tags: [triggers, positive, test]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

implement per-API-key rate limiting for the public API in api/app.py, 100 requests a minute, returning 429 with Retry-After
