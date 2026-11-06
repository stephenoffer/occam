"""The worker process: `python -m grainbank.worker --help`."""

import argparse
import importlib
import json
import sys
from pathlib import Path

from .taskapp import UnknownTask, app

AUTODISCOVER = ("grainbank.settlement",)


def load_tasks():
    for module in AUTODISCOVER:
        importlib.import_module(module)


def run_one(name, args, kwargs=None):
    result = app.run_task(name, *args, **(kwargs or {}))
    return {"task": name, "result": result, "chained": app.drain()}


def build_parser():
    parser = argparse.ArgumentParser(prog="grainbank.worker")
    parser.add_argument("--list", action="store_true", help="print the name of every registered task")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run one task by name")
    run.add_argument("task")
    run.add_argument("--args", default="[]", help="JSON array of arguments")
    drain = sub.add_parser("drain", help="run a file of messages saved from the broker")
    drain.add_argument("messages")
    resume = sub.add_parser("resume", help="finish a nightly close from its checkpoint")
    resume.add_argument("checkpoint")
    resume.add_argument("--ledger", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    load_tasks()
    from . import settlement

    if args.list:
        print("\n".join(app.task_names()))
        return 0
    try:
        if args.command == "run":
            print(json.dumps(run_one(args.task, json.loads(args.args)), indent=2, sort_keys=True))
        elif args.command == "drain":
            messages = json.loads(Path(args.messages).read_text())
            done = [run_one(item["task"], item.get("args", []), item.get("kwargs")) for item in messages]
            print(json.dumps(done, indent=2, sort_keys=True))
        elif args.command == "resume":
            checkpoint = settlement.load_checkpoint(args.checkpoint)
            ledger = settlement.Ledger.load(args.ledger)
            results = checkpoint.resume(ledger)
            ledger.save(args.ledger)
            print(json.dumps({"season": checkpoint.season, "settled": [r.ticket_id for r in results]}, sort_keys=True))
        else:
            build_parser().print_help()
    except (UnknownTask, settlement.GrainbankError) as exc:
        print(f"error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
