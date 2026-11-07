# ADR 0001: Decimal hours and quarter-hour rounding

Date: 2024-03-11. Status: accepted.

## Context

The first pay script used floats and minutes-as-fractions. A worker with 37 shifts of 7h50m was paid a
penny short because 7.8333... hours didn't add up, and the bureau's trailer check rejected the file.

## Decision

- Hours and money are `Decimal` everywhere in Python.
- Each shift's worked time is rounded to the nearest quarter hour once, when it's read.
- Money rounds to the penny half up, once per payslip line.
- SQL can't hold Decimals, so SQL works in whole minutes and whole pence and rounds at the end.

## Consequences

Totals reconcile with the bureau. Hours print with two places (`7.75`), which payroll prefers to h:mm.
