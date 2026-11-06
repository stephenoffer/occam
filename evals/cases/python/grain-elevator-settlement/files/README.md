# grainbank

Settlement software for the co-op's grain elevators. Scale tickets come in overnight from the elevators.
The nightly close grades and prices them, posts them to member ledgers and writes member statements.

## Running it

Everything runs through the worker:

    python -m grainbank.worker --list
    python -m grainbank.worker run grainbank.settlement.nightly_close --args '["tickets.json", "ledger.json", "statements/"]'
    python -m grainbank.worker drain deploy/inflight_sample.json
    python -m grainbank.worker resume checkpoint.pkl --ledger ledger.json

Set `GRAINBANK_FEED_URL` and `GRAINBANK_ALERT_URL` to point at something other than production.

## Deployment

`deploy/beat_schedule.json` is loaded into the scheduler when an environment is created, and
`deploy/inflight_sample.json` is a sample of what the broker holds at any moment. Workers are upgraded
one elevator at a time, so messages outlive any one release.

A close that dies part way leaves a pickled checkpoint, and a restarted worker finishes it with `resume`.
`tests/fixtures/` has checkpoints kept from real closes in earlier seasons.

## Other teams

`integrations/` has copies of code other teams run against this package, kept here so we can see how it's
used. They own it, and their copies don't change when ours do.

Run the tests with `pytest`.
