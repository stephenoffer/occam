# ADR 0001: Keep the index as one JSON file per clone

Date: 2025-12-15. Status: accepted.

## Context

Searching the full handbook by reading every page took about four seconds on a typical laptop,
mostly in reading and tokenizing about 900 pages. People search many times a day and the chat bot
answers dozens of questions an hour.

## Decision

Save the per-page term counts in `ROOT/.findoc/index.json`, one file per clone, written by
`findoc reindex` and read by search. Keep a layout number in the file and ignore files with any
other layout, so a release that stores something different never reads an old file as if it were
new. Don't use SQLite: the whole file loads in about 60 ms, it's easy to inspect when a result
looks wrong, and there's nothing to migrate.

We tried tuning BM25's k1 and b against twenty saved searches from the chat bot. Nothing beat the
defaults (k1 1.2, b 0.75) by more than one place in any result list, so the defaults stay.

## Consequences

- Each clone builds its own index. The git hook keeps it current after pulls.
- A search on a clone without an index still works, just slowly.
