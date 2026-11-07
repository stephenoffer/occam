# ADR 0002: Naive local times

Status: accepted, March 2025

## Context

All three clinics are in Scotland and every user, patient and clinician deals in UK
wall-clock time. The clocks change twice a year, which only matters for appointments in
the hour that repeats or vanishes, and the clinics are closed then.

## Decision

Store and compare times as naive local times, as ISO strings to the minute. Never attach
an offset. Comparing the strings compares the times, which the SQL relies on.

## Consequences

Arithmetic across a clock change can be an hour out. Nothing in the clinic depends on that.
If we ever open a clinic outside the UK this has to be revisited.
