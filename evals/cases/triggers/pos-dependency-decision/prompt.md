---
tags: [triggers, positive, test]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

should we bring in pydantic to validate webhook payloads or keep the hand rolled checks in api/webhooks.py? look at what we have, decide, and make the change
