"""python -m billing --db PATH <command>

    run [--at ISO] [--fees PATH]     raise every charge that is due (the nightly run)
    statement PATIENT                 charges raised for one patient
"""

from __future__ import annotations

import sys
from datetime import datetime

from billing.fees import DEFAULT_FEES, load_fees
from billing.run import run_charges
from billing.statements import statement
from clinicdb.connect import open_db
from common.cli import add_json_flag, emit, parser
from common.clock import parse_at
from common.money import pounds


def main(argv: list[str] | None = None) -> int:
    top = parser("billing", "Raise charges and print statements.")
    commands = top.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--at")
    run.add_argument("--fees", default=str(DEFAULT_FEES))
    add_json_flag(run)
    show = commands.add_parser("statement")
    show.add_argument("patient", type=int)
    add_json_flag(show)
    args = top.parse_args(argv)

    db = open_db(args.db)
    if args.command == "run":
        run_at = parse_at(args.at) if args.at else datetime.now().replace(second=0, microsecond=0)
        charges = run_charges(db, run_at, load_fees(args.fees))
        total = sum(charge.amount_pence for charge in charges)
        payload = {"run_at": run_at.isoformat(timespec="minutes"), "charges": [c.as_dict() for c in charges],
                   "total_pence": total}
        emit(payload, args.json, f"Raised {len(charges)} charges, {pounds(total)}")
    else:
        built = statement(db, args.patient)
        emit(built.as_dict(), args.json, built.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
