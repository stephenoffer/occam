---
tags: [e2e]
max_turns: 40
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`listUsers` in `src/users.js` treats a limit of 0 as if no limit was given, so `listUsers(all, 0)` returns everyone. It should return nobody. Please fix it.
