---
tags: [regression]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

The nightly job now generates run sheets with about 200,000 steps and `python -m runsheet order` on one of those never finishes, I killed it after an hour. `waves` and `subset` are just as bad. All three need to finish in under 5 seconds on a sheet that size, whatever order the generator happens to write the steps in, and that goes for sheets that turn out to be invalid too. No new dependencies. Keep the API as it is.
