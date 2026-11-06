---
tags: [python]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Finance wants our exchange rates to be date-effective. Right now `spot_rate(base, quote)` in `tidewater/core/fx.py` always gives you the newest row in `core/data/fx_rates.csv`, so anything back-dated gets priced at today's rate.

Please change it to `spot_rate(base, quote, as_of)`, where `as_of` is a required `datetime.date` with no default. It should return the rate in force on that date, and raise the existing `RateUnavailable` if nothing had been published yet. Then sort out everything that uses it, so that every document is priced at its own business date. The README has a table of which date field each document uses, and results should keep coming out of `python -m tidewater <command> <file>` the way they do now. Contract rates stay as they are.

This is used all over and I don't have a list of where. The repo is much too big for anyone to read end to end, so you'll need to work out what's affected. CI has to stay happy, see CONTRIBUTING.md. When you're done tell me what you changed and how sure you are that you've got everything.
