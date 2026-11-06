import heapq
import json
import tempfile

CHUNK_RECORDS = 100_000


def read_lines(path):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def dedupe(records):
    seen = set()
    for record in records:
        event_id = record["event_id"]
        if event_id not in seen:
            seen.add(event_id)
            yield record


def _sort_key(line):
    record = json.loads(line)
    return (record["ts"], record["event_id"])


def _spill(chunk, runs):
    chunk.sort()
    run = tempfile.TemporaryFile("w+", encoding="utf-8")
    run.writelines(f"{json.dumps(list(key))}\t{line}\n" for key, line in chunk)
    run.seek(0)
    runs.append(run)


def external_sort(records):
    """Sort by (ts, event_id), keeping at most CHUNK_RECORDS records in memory."""
    runs, chunk = [], []
    for record in records:
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        chunk.append(((record["ts"], record["event_id"]), line))
        if len(chunk) >= CHUNK_RECORDS:
            _spill(chunk, runs)
            chunk = []
    if chunk:
        _spill(chunk, runs)

    def stream(run):
        for row in run:
            key, line = row.rstrip("\n").split("\t", 1)
            yield tuple(json.loads(key)), line

    try:
        yield from (line for _, line in heapq.merge(*(stream(run) for run in runs)))
    finally:
        for run in runs:
            run.close()


def run(input_path, output_path):
    with open(output_path, "w", encoding="utf-8") as handle:
        for line in external_sort(dedupe(read_lines(input_path))):
            handle.write(line + "\n")
