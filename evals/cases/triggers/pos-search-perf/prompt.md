---
tags: [triggers, positive, test]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Our /search endpoint has a p95 of about 4 seconds now that products is around 2M rows. Find out why and make it fast.
