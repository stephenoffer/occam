---
tags: [smoke]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

`bulkfetch.fetcher.fetch_all` needs to be safe for how we use it now. We feed it up to 50,000 URLs, sometimes from a generator, and the service runs other coroutines on the same event loop. Today the process balloons in memory, the service's heartbeat stalls during a run, and when our shutdown path cancels a run, requests keep going.

Keep the signature `fetch_all(urls, transport, *, max_concurrency=20, enrich=enrich_record)` and the `Result` type. Results stay in input order and one failed URL must not stop the others. A cancelled run should stop promptly and raise `CancelledError` to the caller. `enrich_record` is CPU-heavy. There's already a semaphore in there, so I'd guess it mostly needs a lower default.
