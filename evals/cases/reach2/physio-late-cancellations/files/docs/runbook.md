# Runbook

## Nightly jobs

`scripts/nightly.sh` runs from cron on the clinic server:

| When | Job | Command |
|---|---|---|
| 02:00 daily | Charge run | `python -m billing --db /srv/kestrel/clinic.db run` |
| 18:00 daily | Reminder texts | `python -m messaging --db /srv/kestrel/clinic.db reminders` |
| 06:00 on the 1st | Monthly figures | `python -m reports --db /srv/kestrel/clinic.db monthly --month <last month>` |

## If the charge run fails

It's safe to rerun: nothing is charged twice. Rerun it by hand with `--at` set to the
time the failed run should have used, so nothing that fell due after it is picked up early.

## If reminders didn't go out

Check `python -m messaging --db ... pending`. If the messages are queued, the SMS sender
service is the problem, not this repository.

## Restoring the database

Nightly backups are in `/srv/kestrel/backups`. Stop cron, copy the backup over
`clinic.db`, start cron, then rerun the charge run.
