# Kestrel Physio clinic system

Bookings, charges and clinic figures for Kestrel Physio's three clinics. Reception uses it
through the desk app (a separate repository) which calls the same commands as the CLIs
below; the nightly jobs run from cron on the clinic server.

## Packages

| Package | What it does |
|---|---|
| `appointments` | Booking and the appointment lifecycle: book, confirm, check in, complete, cancel, no-show. |
| `scheduling` | Clinicians' weekly sessions and the free slots in them. |
| `patients` | Patient records, phone number handling, and the rules for booking online. |
| `billing` | The nightly charge run (treatment fees for self-funded patients, DNA fees) and patient statements. |
| `reports` | Monthly figures per clinician for the clinical leads: bookings, attendance, cancellations, DNA rate. |
| `messaging` | Text messages to patients: booking and cancellation confirmations, the evening reminder run. |
| `clinicdb` | The SQLite schema, opening the database, and seed data. |
| `common` | Times, money and CLI helpers. |

## Running it

Everything is standard-library Python 3.10+. Each package has a command line:

```sh
python -m clinicdb --db var/clinic.db init
python -m clinicdb --db var/clinic.db seed data/demo_seed.json
python -m appointments --db var/clinic.db book --patient 1 --clinician 1 --start 2026-12-08T10:00
python -m scheduling --db var/clinic.db free 1 2026-12-08
python -m billing --db var/clinic.db run
python -m reports --db var/clinic.db monthly --month 2026-12
```

Add `--json` to any command for machine-readable output; the desk app uses that.
Times are local wall-clock times to the minute, like `2026-12-08T10:00`.

## Tests

```sh
python -m pytest -q
```

## Further reading

- `docs/architecture.md`: how the pieces fit together.
- `docs/glossary.md`: the clinic's vocabulary.
- `docs/runbook.md`: the nightly jobs and what to do when one fails.
- `docs/adr/`: decisions we've made and why.
