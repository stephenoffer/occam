---
tags: [reach]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

The orders API now sends `discount_cents` on every order. Can you show it in `cli/show_order.py` when it isn't zero? An order with a discount should read like `Order 7: $12.00 (paid, $1.50 off)`. One without a discount stays as it is now.
