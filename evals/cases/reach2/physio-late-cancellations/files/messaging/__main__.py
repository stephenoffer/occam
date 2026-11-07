"""python -m messaging --db PATH {reminders [--at ISO], pending} [--json]"""

from __future__ import annotations

import sys
from datetime import datetime

from clinicdb.connect import open_db
from common.cli import add_json_flag, emit, parser
from common.clock import parse_at
from messaging.outbox import pending
from messaging.reminders import send_reminders


def main(argv: list[str] | None = None) -> int:
    top = parser("messaging", "Queue and inspect patient text messages.")
    commands = top.add_subparsers(dest="command", required=True)
    remind = commands.add_parser("reminders", help="queue reminders for tomorrow's appointments")
    remind.add_argument("--at")
    add_json_flag(remind)
    waiting = commands.add_parser("pending", help="messages not yet sent")
    add_json_flag(waiting)
    args = top.parse_args(argv)

    db = open_db(args.db)
    if args.command == "reminders":
        now = parse_at(args.at) if args.at else datetime.now().replace(second=0, microsecond=0)
        queued = send_reminders(db, now)
        emit({"queued": queued}, args.json, f"Queued {len(queued)} reminders")
    else:
        messages = pending(db)
        emit(messages, args.json, "\n".join(f"{m['id']:>5} {m['template']:<10} {m['body']}" for m in messages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
