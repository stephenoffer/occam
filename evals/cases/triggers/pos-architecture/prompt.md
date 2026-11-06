---
tags: [triggers, positive, test]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

notifications/service.py reaches straight into the db and smtp. I want notifications behind a proper boundary so we can swap the email provider. Restructure it.
