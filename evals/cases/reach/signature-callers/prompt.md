---
tags: [reach]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

We're starting to sell in Europe and Japan, and prices still come out in dollars everywhere. `format_price` in `shopfront/pricing/money.py` only knows USD.

Please change it to take the currency as a required second argument, `format_price(minor_units, currency)`, formatting by the table in the README, and raising `ValueError` for a currency that isn't in it. Every order, item and product already carries its `currency`, so everything that shows a price should show it in that currency.
