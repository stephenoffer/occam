import argparse
import dataclasses
import json
from datetime import date
from pathlib import Path

from toolhire.models import Rental
from toolhire.settlement import settle_return


def main() -> None:
    parser = argparse.ArgumentParser(prog="toolhire")
    commands = parser.add_subparsers(dest="command", required=True)
    settle = commands.add_parser("settle")
    settle.add_argument("--rental", required=True, type=Path)
    settle.add_argument("--returned-on", required=True, type=date.fromisoformat)
    settle.add_argument("--damage-cents", type=int, default=0)
    args = parser.parse_args()
    raw = json.loads(args.rental.read_text())
    rental = Rental(raw["rental_id"], raw["customer"], raw["tool_class"], date.fromisoformat(raw["start_on"]),
                    date.fromisoformat(raw["due_on"]), raw["deposit_cents"])
    print(json.dumps(dataclasses.asdict(settle_return(rental, args.returned_on, args.damage_cents))))


if __name__ == "__main__":
    main()
