"""python -m patients --db PATH <command>

    register NAME [--phone P] [--email E] [--funding self|insurer] [--on DAY]
    show ID
    find TEXT
    deposit ID [--on DAY]      whether online booking needs a deposit
"""

from __future__ import annotations

import sys
from datetime import date

from clinicdb.connect import open_db
from common.cli import add_json_flag, emit, fail, parser
from common.clock import parse_day
from patients.policy import deposit_decision
from patients.registry import find, get, register


def main(argv: list[str] | None = None) -> int:
    top = parser("patients", "Patient records and booking rules.")
    commands = top.add_subparsers(dest="command", required=True)
    new = commands.add_parser("register")
    new.add_argument("name")
    new.add_argument("--phone")
    new.add_argument("--email")
    new.add_argument("--funding", default="self")
    new.add_argument("--on")
    add_json_flag(new)
    show = commands.add_parser("show")
    show.add_argument("id", type=int)
    add_json_flag(show)
    search = commands.add_parser("find")
    search.add_argument("text")
    add_json_flag(search)
    deposit = commands.add_parser("deposit")
    deposit.add_argument("id", type=int)
    deposit.add_argument("--on")
    add_json_flag(deposit)
    args = top.parse_args(argv)

    db = open_db(args.db)
    on = parse_day(args.on) if getattr(args, "on", None) else date.today()
    try:
        if args.command == "register":
            patient = register(db, args.name, on, args.phone, args.email, args.funding)
            emit(patient.as_dict(), args.json, f"Registered patient {patient.id}")
        elif args.command == "show":
            patient = get(db, args.id)
            emit(patient.as_dict(), args.json, f"{patient.id} {patient.name} ({patient.funding})")
        elif args.command == "find":
            found = find(db, args.text)
            emit([p.as_dict() for p in found], args.json, "\n".join(f"{p.id} {p.name}" for p in found) or "No match.")
        else:
            get(db, args.id)
            decision = deposit_decision(db, args.id, on)
            verdict = "needs a deposit" if decision.needs_deposit else "can book online without a deposit"
            emit(decision.as_dict(), args.json, f"Patient {args.id} {verdict} ({decision.no_shows} since {decision.since})")
    except (LookupError, ValueError) as error:
        return fail(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
