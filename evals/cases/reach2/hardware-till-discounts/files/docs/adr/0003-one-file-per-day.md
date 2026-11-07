# ADR 0003: One sales file per trading day

Status: accepted, March 2024

## Context

The till needs to write each sale durably the moment it completes (power cuts happen), and the day's
sales need to be easy to move off the till.

## Decision

Each completed sale is appended as one JSON line to that day's file, flushed and synced before the
receipt prints. Nothing ever rewrites a line. The day is the calendar day of the sale's completion
time; we don't trade past midnight.

## Consequences

- Sale numbers restart each day, so a sale reference includes the date.
- Closing the day is a file copy.
