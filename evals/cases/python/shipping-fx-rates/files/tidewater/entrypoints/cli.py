"""python -m tidewater <command> <document.json>"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from tidewater.core.errors import TidewaterError
from tidewater.services.berth_desk import berth_charge
from tidewater.services.claims_desk import assess_claim
from tidewater.services.closing import close_period
from tidewater.services.documents import Document
from tidewater.services.filing import file_declaration
from tidewater.services.invoicing import invoice
from tidewater.services.quoting import quote
from tidewater.services.settlements import settle

Handler = Callable[[Document], dict[str, object]]
HANDLERS: dict[str, Handler] = {
    "quote": quote,
    "invoice": invoice,
    "settlement": settle,
    "declaration": file_declaration,
    "claim": assess_claim,
    "closing": close_period,
    "berth-charge": berth_charge,
}


def run_batch(path: Path) -> list[dict[str, object]]:
    return [HANDLERS[entry["kind"]](entry["doc"]) for entry in json.loads(path.read_text())]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tidewater")
    parser.add_argument("command", choices=[*HANDLERS, "batch"])
    parser.add_argument("document", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "batch":
            print(json.dumps(run_batch(args.document), indent=2))
        else:
            print(json.dumps(HANDLERS[args.command](json.loads(args.document.read_text())), indent=2))
    except TidewaterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
