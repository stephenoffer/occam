---
name: occam-sql
description: SQL guidance on injection, dialect differences, NULL logic, join grain, time, money and collation semantics, transactions, query plans, migrations. Use alongside occam to write, debug or review SQL or schema changes where these matter.
---

# SQL

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Injection:** use parameters. Dynamic identifiers need an allow-list, since parameters can't bind them.
- **Dialect:** check the actual engine and version. Type affinity, `NULL` ordering, collation, date functions, and integer versus real division all differ.
- **NULL:** three-valued logic means `NOT IN` with a NULL returns no rows, and aggregates skip NULLs. `COUNT(*)` and `COUNT(col)` differ.
- **Joins and grouping:** a one-to-many join multiplies rows and silently inflates sums. Check the grain before aggregating.
- **Time, money and text:** store money as integer minor units or an exact decimal, not float. Be explicit about timezone and what a day boundary means. Text ordering and comparison depend on collation, and ISO date strings sort correctly only when uniformly formatted.
- **Transactions and plans:** know the isolation level, wrap multi-statement changes, and consider lock duration in migrations. Read the query plan for anything large, and ship schema and code changes in a deployable order, with a backfill plan.
- **Concurrent writers:** Read Committed allows lost updates, and Repeatable Read still allows write skew, plus lost updates in MySQL, where PostgreSQL aborts the second writer instead. Pick the level or the lock for the invariant. Update a counter in one statement (`SET n = n + 1`) or lock the row with `SELECT ... FOR UPDATE`. Enforce uniqueness with a unique constraint and handle the violation, since checking first races. Retry the whole transaction, a bounded number of times, on serialization failures and deadlocks (40001 and 40P01 in PostgreSQL). Keep network calls out of an open transaction: write an outbox row and act after commit.
- **Keys and pages:** give each foreign key a deliberate `ON DELETE`, and check what it does to soft-deleted rows. Page on a unique sort key with a keyset cursor, since `OFFSET` over changing rows skips and repeats, and `LIMIT` without `ORDER BY` returns any rows at all. Add an index for a query you've seen in `EXPLAIN`, matching its filter and sort, since each index slows writes.
- **Renames and timestamps:** a rename breaks the code still running from the last deploy, so add, backfill, switch readers, then drop. Store timestamps with a timezone, or as integers in a stated unit, and check that precision survives the driver round trip.
- **Wrong without an error:** a comparison that expects one row from a subquery that can return several, and a filter on a value the column never holds, both return something plausible. Look at the real values with a query before relying on them, and on a partitioned table, filter on the partition key.
- **Testing:** exercise the query on data that contains NULLs, duplicates, ties and boundary timestamps, because sample data usually hides exactly these.
- **What generated code gets wrong here:** SQL assembled from strings, `SELECT *`, an `UPDATE` or `DELETE` without `WHERE`, `NOT IN` over nullable subqueries, floats for money, queries that work on sample data and scan a whole table in production, functions from another dialect, and migrations with no rollback or a lock on a large table. Run `EXPLAIN` on the real engine, because the scanner can't see the data.
