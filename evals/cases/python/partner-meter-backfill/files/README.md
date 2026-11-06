# meterhub

Rolls smart-meter readings up into per-station CSVs for billing, and hands them to the billing uplink.

    python3 -m meterhub nightly --date 2026-01-05 --data-dir /var/lib/meterhub /var/spool/collector/2026-01-05.npz

## How a run works

1. The collector fleet writes one archive a day (`meterhub/archive.py`).
2. Readings are normalised (`meterhub/readings.py`) and rolled up per station (`meterhub/rollup.py`).
3. Each station's rollup is written to `<data-dir>/rollups/<source>/<station>.csv`, with columns `period,kwh` (`meterhub/store.py`).
4. `tools/push-rollups` delivers the finished set to the spool named by `METERHUB_SPOOL` (`meterhub/uplink.py`).

## Operations

cron alerts on the exit status. A run exits non-zero if anything failed to load, roll up, write or deliver. Billing works from whatever arrives, so a partial load that reports success turns into a wrong invoice.

Run the tests with `python3 -m pytest`. Versions are pinned in `requirements.lock`.
