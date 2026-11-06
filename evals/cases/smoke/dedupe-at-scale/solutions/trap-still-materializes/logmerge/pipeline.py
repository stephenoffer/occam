import json


def read_records(path):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def dedupe(records):
    seen = set()
    for record in records:
        if record["event_id"] not in seen:
            seen.add(record["event_id"])
            yield record


def run(input_path, output_path):
    records = sorted(dedupe(read_records(input_path)), key=lambda record: (record["ts"], record["event_id"]))
    with open(output_path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
