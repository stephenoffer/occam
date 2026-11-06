---
tags: [e2e]
max_turns: 40
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`fetcher.fetch_all(urls)` should stop everything promptly when the caller cancels it, but right now cancellation gets swallowed and requests keep going. Please fix it.
