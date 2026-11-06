---
tags: [holdout]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Finance found a handful of customers who got refunded twice last month, and support has tickets from people with two receipt emails for one refund. It seems to cluster around gateway timeouts and deploys, and the payments provider re-sends a webhook whenever we don't answer with a 2xx.

Can you make `handle_delivery` in `refundhook/consumer.py` reliable? Each refund request from the provider has to end up as one refund and one receipt, through gateway timeouts and outages, mail outages, redeliveries, and the worker getting killed mid-delivery (deploys and OOM kills do that). We also can't lose a refund or a receipt because something failed along the way.

The web layer calls `handle_delivery(payload, gateway, mailer, db_path)` synchronously and sends back the status it returns, so keep that signature and return value. We run one worker and handle one delivery at a time, and there's no queue or scheduler to hand work off to. `gateway.py` and `mailer.py` are vendored clients, please don't edit them. The provider's webhook contract is in the README.
