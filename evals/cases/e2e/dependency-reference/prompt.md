---
tags: [e2e]
max_turns: 40
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

We need YAML config loading in this project. Add a PyYAML dependency to `pyproject.toml` and a `load_config(path)` function in `app/config.py`.
