# crmsync

Copies contacts, companies and deals from our CRM vendor into a local SQLite database. Runs nightly.

    python -m crmsync --base-url https://api.example-crm.invalid --token $CRM_TOKEN --db crm.db
    python -m crmsync --sandbox --db crm.db     # against the vendor's sandbox

The nightly job alerts on the exit code: **exit status is non-zero whenever the vendor returns
anything we can't use**, because a partial sync that looks successful is worse than a failed one.

Run the tests with `pytest`.
