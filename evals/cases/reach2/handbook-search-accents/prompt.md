---
tags: [reach2]
max_turns: 60
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

Search in findoc ignores case but not accents, and it keeps tripping people up. Searching for cafe doesn't find the Café opening hours page, and zurich finds nothing about the Zürich office. Please make search accent-insensitive in both directions, so cafe finds café and café finds cafe, the same way Cafe and cafe already find each other. Words matched like that should be highlighted in the result snippets like any other match.

Everyone runs `python -m findoc search` against their own checkout of the handbook, so that's the behaviour that matters.
