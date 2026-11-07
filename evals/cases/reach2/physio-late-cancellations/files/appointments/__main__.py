"""python -m appointments --db PATH <command>

    book --patient P --clinician C --start ISO [--minutes N] [--at ISO]
    confirm|arrive|complete|cancel|no-show ID [--at ISO]
    show ID
    history PATIENT

``--at`` is when the action happens (defaults to now). Add ``--json`` for JSON output.
"""

from __future__ import annotations

import sys
from datetime import datetime

from appointments import queries, service
from appointments.errors import AppointmentError
from clinicdb.connect import open_db
from common.cli import add_json_flag, emit, fail, parser
from common.clock import human, parse_at

ACTIONS = {
    "confirm": service.confirm,
    "arrive": service.arrive,
    "complete": service.complete,
    "cancel": service.cancel,
    "no-show": service.mark_no_show,
}


def main(argv: list[str] | None = None) -> int:
    top = parser("appointments", "Book appointments and move them through their lifecycle.")
    commands = top.add_subparsers(dest="command", required=True)

    book = commands.add_parser("book")
    book.add_argument("--patient", type=int, required=True)
    book.add_argument("--clinician", type=int, required=True)
    book.add_argument("--start", required=True)
    book.add_argument("--minutes", type=int)
    book.add_argument("--at")
    add_json_flag(book)

    for name in ACTIONS:
        action = commands.add_parser(name)
        action.add_argument("id", type=int)
        action.add_argument("--at")
        add_json_flag(action)

    show = commands.add_parser("show")
    show.add_argument("id", type=int)
    add_json_flag(show)

    history = commands.add_parser("history")
    history.add_argument("patient", type=int)
    add_json_flag(history)

    args = top.parse_args(argv)
    db = open_db(args.db)
    at = parse_at(args.at) if getattr(args, "at", None) else datetime.now().replace(second=0, microsecond=0)

    try:
        if args.command == "book":
            appointment = service.book(db, args.patient, args.clinician, parse_at(args.start), at, args.minutes)
            emit(appointment.as_dict(), args.json, f"Booked {appointment.id}: {human(appointment.starts_at)}")
        elif args.command in ACTIONS:
            appointment = ACTIONS[args.command](db, args.id, at)
            emit(appointment.as_dict(), args.json, f"Appointment {appointment.id} is now {appointment.status.label}")
        elif args.command == "show":
            appointment = queries.get(db, args.id)
            emit(appointment.as_dict(), args.json, _line(appointment))
        else:
            appointments = queries.for_patient(db, args.patient)
            payload = {"patient_id": args.patient, "appointments": [a.as_dict() for a in appointments]}
            emit(payload, args.json, "\n".join(_line(a) for a in appointments) or "No appointments.")
    except AppointmentError as error:
        return fail(str(error))
    return 0


def _line(appointment: queries.Appointment) -> str:
    return f"{appointment.id:>5}  {human(appointment.starts_at)}  clinician {appointment.clinician_id}  {appointment.status.label}"


if __name__ == "__main__":
    sys.exit(main())
