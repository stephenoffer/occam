---
tags: [python]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

The ops team wants a tide calendar they can pull up in their notebook: for one site, for each local day in a date range, every high and low the gauge saw that day, with the heights relative to chart datum. `daily_extrema` isn't it, because it only gives one high and one low per day and most of our sites get two of each. The dashboards depend on `daily_extrema` as it is, so leave it alone.

Make it a public function exported from `tidekit` like the others, in a new module, since `summary.py` is long enough already. The notebook will call it positionally with the site code, the list of readings (which can include other sites), the dict of datum offsets for all sites, the site's timezone name, and the first and last day as `datetime.date`s, both inclusive. It should return a dict mapping every day in the range to a list of `TideEvent`s in time order, with an empty list for a day when nothing happened.

`./check.sh` has to be green before this can go in. It's been red since Friday's merge and I haven't looked at why.
