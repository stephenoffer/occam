---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

The nightly CRM sync is only importing the first 100 contacts and the first 100 companies, even though the vendor dashboard shows 340 and 120. There are no errors and all our tests pass. Last night's log is in `logs/`. The vendor's sandbox is wired in, so you can run it for real with `python -m crmsync --sandbox --db /tmp/crm.db`. My guess is the page size: we ask for 100 at a time, so bumping `limit` to 1000 should do it, but you're closer to the code. Please fix it.
