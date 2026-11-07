# Contributing

- Python 3.10+, standard library only. The clinic server has no internet access, so no
  third-party packages.
- Run `python -m pytest -q` before pushing. New behaviour comes with a test.
- Every status change goes through `appointments.service._move`, so that
  `appointment_events` stays a complete history. Don't update `appointments.status`
  anywhere else.
- SQL that is more than a lookup lives in a `.sql` file beside the module that runs it,
  so it can be read and run on its own.
- Times are naive local times (docs/adr/0002-naive-local-times.md). Don't introduce
  time zones in one place.
- Money is integer pence. Format it with `common.money.pounds` only at the edge.
- CLI output with `--json` is used by the desk app: add fields freely, but don't rename or
  remove them without talking to the desk app team.
