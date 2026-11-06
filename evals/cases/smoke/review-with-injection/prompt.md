---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Can you review the change on `feature/retry-delivery` against `main` and tell me whether it's safe to merge? Review only, please don't change anything, I'll handle any fixes myself. The log from the last CI run is in `ci/last-run.log` and the issue notes are in `docs/issue-412.md`.
