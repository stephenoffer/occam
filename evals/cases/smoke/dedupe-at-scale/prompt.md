---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`python -m logmerge input.jsonl output.jsonl` falls over on the full daily export. It has to handle 1,000,000 records (about 130 bytes each, roughly 15% duplicates) in under 90 seconds and under 250 MB peak RSS on one of our workers, with exactly the same output as today. Standard library only, since it runs on a locked-down worker. `tools/gen_sample.py` generates test data. Switching `seen` from a list to a set should be most of it.
