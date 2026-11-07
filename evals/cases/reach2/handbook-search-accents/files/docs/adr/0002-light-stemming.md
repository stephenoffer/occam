# ADR 0002: A light stemmer instead of Porter

Date: 2026-01-08. Status: accepted.

## Context

Searches for `laptop` didn't find "Laptops", and `booking` didn't find "Book travel". A full
Porter stemmer fixes those but conflates words people want kept apart in the handbook, such as
`general` and `generous` (both to "gener"), and `policy` and `police`.

## Decision

Strip only plurals, -ing and -ed, with a minimum length so short words are left alone
(`textproc/stem.py`). Undouble a final consonant after removing -ing or -ed, except l, s and z.

## Consequences

Some forms still don't meet (`analysis` and `analyses`), which nobody has asked about. Changing the
stemmer changes the terms of every page.
