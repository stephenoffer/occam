# Architecture

One SQLite database (`clinicdb/schema.sql`) on the clinic server, and a package per area of
the business. The desk app and cron both call the packages' command lines.

```
desk app ──> appointments ──> scheduling (is the slot free?)
                 │
                 └──> messaging (confirmation texts)

cron 02:00 ──> billing run      (reads appointments, writes charges)
cron 18:00 ──> messaging reminders
1st of month ──> reports monthly (emailed to the clinical leads)
```

## Appointments

An appointment's status moves through `appointments/status.py`'s transitions:

```
booked ─> confirmed ─> arrived ─> completed
   │          │
   ├──────────┴─> cancelled      (before the start)
   └──────────┴─> no_show        (after the start)
```

Statuses are stored as integers (ADR 0001). `appointment_events` keeps every change.

## Charges

The charge run looks for what has fallen due since the last run and raises one charge per
appointment and kind. It never changes a charge once raised: refunds and write-offs are done
in the accounts package, not here.

## Figures

`reports` turns a month of appointments into per-clinician figures. The counting is done in
SQL so the practice manager can rerun it by hand.
