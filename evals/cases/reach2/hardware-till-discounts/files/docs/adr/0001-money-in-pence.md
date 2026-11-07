# ADR 0001: Money is whole pence everywhere

Status: accepted, January 2024

## Context

The old till software stored prices as floating-point pounds. Summing a busy Saturday gave totals
a penny out, and finance spent part of every Monday finding out which penny.

## Decision

Every amount of money is an integer number of pence: prices, line totals, tenders, change, floats,
and every file we write. Formatting to pounds happens only when printing for a person.

## Consequences

- Quantity times unit price is exact. Anything that divides money (splitting a multibuy price,
  percentages) must say how it rounds, in the code and in its tests.
- The CLI accepts amounts like `245.10` and converts them straight away with `till.money.parse`.
