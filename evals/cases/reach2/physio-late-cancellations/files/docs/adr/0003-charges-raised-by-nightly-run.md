# ADR 0003: Charges are raised by a nightly run, not at the moment of the event

Status: accepted, June 2025

## Context

Reception corrects mistakes during the day: a patient marked as DNA who turns up twenty
minutes late, a treatment completed on the wrong appointment. Charging at the moment of the
event meant refunding and recharging several times a week.

## Decision

Charges are raised once a night by `billing`, for everything that has fallen due. Each
kind of charge has a query that decides what is due.

## Consequences

A charge appears the morning after. Corrections made the same day never reach the patient.
