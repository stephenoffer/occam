# logmerge

Merges event logs into one clean file.

    python -m logmerge input.jsonl output.jsonl

Input is one JSON object per line, each with an `event_id` and a numeric `ts`.

Output:

- One record per `event_id`. When an event appears more than once, the first occurrence in the input wins.
- Sorted by `ts`, then by `event_id`.
- One JSON object per line with sorted keys, non-ASCII text kept as-is.

INPUT and OUTPUT may be the same file, which is how the nightly job runs it. The output file is only
replaced once the whole run has succeeded: if the input turns out to be bad, the job exits non-zero
and the previous output is left as it was.

Run the tests with `pytest`.
