# tidekit

Tide gauge reductions for the harbour authority's ops desk. Gauges report water levels to the
harbour export (`https://export.harbour.invalid`), and tidekit turns those readings into the tide
figures the desk publishes.

## Vocabulary

| Term | Meaning |
|---|---|
| station | A place with a gauge, identified by a code such as `HLX`. |
| reading | One water level from a station's gauge at a moment in time. |
| level | A water level in metres. Names carry the unit, as in `level_m`. |
| chart datum | The reference level published charts use. |
| offset | How far a gauge's zero sits above chart datum, in metres. |
| high water, low water | The two kinds of tide event. |
| turning point | A reading where the tide changes direction, which makes it a tide event. |

## Layout

- `readings.py`: the harbour export and how to select from it
- `datum.py`: reducing levels to chart datum
- `events.py`: tide events
- `summary.py`: the desk's published figures
- `harmonics.py`: predicted levels from tidal constituents
- `nightly.py`: the month-to-date job

## The nightly job

Cron runs the job as a script from the repository root:

    PYTHONPATH=. python3 tidekit/nightly.py --export data/harbour-export.csv --offsets data/datum_offsets.json

## Checks

`./check.sh` runs what CI runs.
