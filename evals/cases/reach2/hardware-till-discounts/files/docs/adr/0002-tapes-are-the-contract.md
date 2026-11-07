# ADR 0002: Head office reads tapes, not store code

Status: accepted, March 2024

## Context

Head office used to read store sales straight out of each store's database over the VPN, using the
store software's own classes. Every till upgrade broke the finance scripts, and finance couldn't
upgrade without upgrading every store first.

## Decision

Stores send head office one file per trading day, the tape, in a format head office documents and
owns (`backoffice/docs/tape-format.md`). The finance server runs `backoffice` on its own; it never
installs or imports store-side packages. Store-side code produces the file; head office has its own
reader and its own checks.

## Consequences

- Head office can upgrade on its own schedule.
- The format has a version number, and head office sets aside records whose version it doesn't
  know instead of guessing.
- There are two readers of the same data, one in each package, with nothing shared between them.
