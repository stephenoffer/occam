# Tape format

Owned by head office. Stores produce tapes; head office reads them.

A tape is a UTF-8 text file named `<store>-<YYYY-MM-DD>.tape` holding one trading day of one
store's sales, one JSON object per line, in the order the sales were rung. Blank lines are ignored.

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Record format version: 1 or 2. |
| `store` | string | Store code, e.g. `BRH01`. Must match the file name. |
| `till` | int | Till number within the store. |
| `sale` | string | Sale reference, unique within the store and day. |
| `at` | string | Local time the sale completed, ISO 8601 to the second. Must fall on the tape's day. |
| `lines` | list | At least one line, see below. |
| `tenders` | list | `{"type": "cash" or "card", "pence": int > 0}` |
| `change` | int | Change given, in pence. |

A line is `{"sku": string, "dept": string, "qty": int >= 1, "unit": int >= 0}`, where `unit` is
the price of one item in pence, VAT included. From version 2 a line may also carry
`"discount": {"pence": int >= 1, "reason": "STAFF" | "PROMO" | "DAMAGED"}`, an amount taken off
that line. A line's value is `qty * unit`, less its discount if it has one.

## Rules head office applies

- Records with a version head office doesn't know are quarantined, not guessed at.
- Fields head office doesn't know are ignored.
- Every sale's lines must total what was paid (all tenders less change). Sales that don't are
  flagged for finance to check before the day is posted.

## Versions

- 1 (March 2024): first version.
- 2 (November 2026): optional line discounts. Version 1 tapes are still accepted; stores move to
  version 2 as their tills are upgraded.
