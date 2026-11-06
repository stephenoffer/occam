"""Run several exports from one job file."""

import json

from .formats.csv_format import export_csv
from .formats.json_format import export_json
from .ledger import filter_rows, load_ledger


def render(name, rows, summary_row=False):
    if name == "csv":
        return export_csv(rows, summary_row=summary_row)
    if name == "json":
        return export_json(rows, summary_row=summary_row)
    raise ValueError(f"unsupported format: {name}")


def run_job(path):
    with open(path) as handle:
        job = json.load(handle)
    rows = load_ledger(job["input"])
    for output in job["outputs"]:
        selected = filter_rows(rows, output.get("currency"))
        with open(output["path"], "w") as target:
            target.write(render(output["format"], selected, output.get("summary_row", False)))
