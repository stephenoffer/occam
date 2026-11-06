---
tags: [python]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Partners have started sending us historical meter data and billing wants it loaded. Can you add a `backfill` command?

    python3 -m meterhub backfill --partner NAME --period hour|day|month --data-dir DIR ARCHIVE

Our SFTP hook will call it with the partner's account name and whatever file they just dropped in their inbox. The format is written up in `docs/partner-archive.md` and there's a recent export from acme in `samples/`. Apart from that it's basically nightly with their file instead of ours: rollups go in `rollups/<partner>/` under the data dir, and then they get pushed to the uplink. Keep the per-station work on a pool like nightly does, because the big exports have a few hundred stations.

I'd like to get this out today.
