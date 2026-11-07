# ADR 0003: Forecasts price planned rosters, not timesheets

Date: 2025-06-02. Status: accepted.

## Context

Estimating used to price bids from last year's timesheets, which carried last year's sickness and
mistakes, and site managers had no way to price a plan before it was worked.

## Decision

`costing` prices a roster: planned shifts by site and worker. It doesn't round to quarter hours, ignore
approval or add allowances, because none of those exist for a plan. Vacant shifts are priced at a vacant
rate. On-costs come from the rates finance publishes each April.

## Consequences

Forecasts and actual pay differ by allowances, rounding and absence, which site managers accept as
the gap between plan and outcome. They should not differ in how a planned hour is priced.
