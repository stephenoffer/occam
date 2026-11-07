# ADR 0002: The wage accrual is worked out in SQL

Date: 2025-01-20. Status: accepted.

## Context

The external auditors sample month-end accruals. For 2024 they asked how each figure was derived, and
following a Python script through four modules took two days of finance's time.

## Decision

The accrual's arithmetic lives in one SQL query, `ledger/sql/wage_accrual.sql`. Python only loads the
inputs into SQLite and formats the result. The archived inputs and the query are what the auditors
re-run; they've confirmed they can read SQL.

## Consequences

- The query must be self-contained: rounding, which hours are premium time and the cost per cost
  centre are all in it, not in Python.
- Finance signs off any change to the query.
- Money is in whole pence and time in minutes inside SQL (ADR 0001).
