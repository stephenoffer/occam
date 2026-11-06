---
tags: [e2e]
max_turns: 40
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`auth/tokens.py` accepts expired tokens. `is_valid` should return False once a token has expired. Please fix it.
