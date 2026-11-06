import json


def read_records(path):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def dedupe(records):
    seen = []
    for record in records:
        if record["event_id"] not in seen:
            seen.append(record["event_id"])
            yield record


def sort_records(records):
    return sorted(records, key=lambda record: (record["ts"], record["event_id"]))


def write_records(records, path):
    text = ""
    for record in records:
        text += json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def run(input_path, output_path):
    write_records(sort_records(dedupe(read_records(input_path))), output_path)
