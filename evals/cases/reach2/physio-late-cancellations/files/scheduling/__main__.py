"""python -m scheduling --db PATH free CLINICIAN DAY [--json]"""

from __future__ import annotations

import sys

from clinicdb.connect import open_db
from common.cli import add_json_flag, emit, fail, parser
from common.clock import parse_day
from scheduling.availability import free_slots


def main(argv: list[str] | None = None) -> int:
    top = parser("scheduling", "Clinicians' free slots.")
    commands = top.add_subparsers(dest="command", required=True)
    free = commands.add_parser("free", help="free slots for a clinician on a day")
    free.add_argument("clinician", type=int)
    free.add_argument("day")
    add_json_flag(free)
    args = top.parse_args(argv)

    db = open_db(args.db)
    day = parse_day(args.day)
    try:
        slots = free_slots(db, args.clinician, day)
    except LookupError as error:
        return fail(str(error))
    times = [slot.strftime("%H:%M") for slot in slots]
    emit({"clinician_id": args.clinician, "day": day.isoformat(), "free": times}, args.json,
         " ".join(times) or "Fully booked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
