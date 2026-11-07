---
tags: [reach]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Partial refunds currently mark the whole order `REFUNDED`, and finance keeps asking which orders were only partly refunded. Please add a `PARTIALLY_REFUNDED` status for a refund smaller than what's left on the order. Refunding the rest later makes it `REFUNDED`. It needs to work in production, which has already run the existing migrations.
