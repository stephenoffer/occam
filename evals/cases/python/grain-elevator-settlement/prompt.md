---
tags: [python]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`grainbank/settlement.py` has become a pain to work in. Please break it up into sensible modules along its natural seams.

This is purely a move: no behavior changes, and nothing outside this repo should have to change because of it. Other teams and the deployed workers depend on this package. Leave the tests as they are, they're how we'll know the move was safe.
