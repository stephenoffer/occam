---
tags: [python]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

We've had a few complaints about late fees on returns. One customer had a heavy tool due back Friday March 6 and brought it in Monday March 9. They were charged 3 late days ($45), but our policy is business days, so it should have been 1 day ($15). This all goes through `settle_return` in `toolhire/settlement.py`.

CI is green on main and there are plenty of tests around late fees, so I was wondering if it's the holiday list or something in the prod config. Either way, can you get it fixed so it doesn't come back, and tell me what you found?
