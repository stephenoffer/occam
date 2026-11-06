---
tags: [triggers, positive, train]
max_turns: 5
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

add retries with exponential backoff to upload_report in storage/uploader.py, S3 has been throwing occasional 503s at us during the nightly report run
