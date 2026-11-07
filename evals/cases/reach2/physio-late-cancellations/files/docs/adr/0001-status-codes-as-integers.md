# ADR 0001: Appointment statuses are stored as integers

Status: accepted, March 2025

## Context

We moved from PracticePro, which stored appointment status as a small integer. Our first
billing and reporting queries were carried over from PracticePro's, and the practice
manager runs some of them by hand against a copy of the database.

## Decision

`appointments.status` is an INTEGER holding PracticePro's codes, and
`appointments.status.Status` is an `IntEnum` with the same values:

| Code | Status | Clinic term |
|---|---|---|
| 1 | booked | booked |
| 2 | confirmed | confirmed |
| 3 | arrived | in clinic |
| 4 | completed | attended |
| 5 | cancelled | cancelled |
| 6 | no_show | DNA |

Codes are never renumbered or reused. A new status gets the next unused code.

## Consequences

Queries written in SQL compare against the codes directly, so they keep working as the
Python names change. The cost is that the codes mean nothing to a reader without this table.
