# Rostering

Site managers plan from named patterns (`rostering/patterns.py`): `days`, `earlies`, `long-days`,
`weekend-cover` and the `four-on-four-off` cycle. `python -m rostering expand` adds a worker's pattern
to a roster file; leave `--worker` out to add vacant shifts.

`python -m rostering check` warns, without stopping anything, when a plan breaks our rostering rules:

- fewer than 11 hours' rest between shifts,
- more than 12 paid hours in one shift,
- more than 6 days in a row,
- more than 60 planned hours in a week.

These are rules about what we plan, agreed with the safety team. How hours are paid is payroll's
business and is in [payroll.md](payroll.md).
