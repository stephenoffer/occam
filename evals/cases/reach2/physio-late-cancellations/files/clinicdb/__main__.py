"""python -m clinicdb --db PATH {init,seed FILE}"""

from __future__ import annotations

import sys

from clinicdb.connect import open_db
from clinicdb.seed import load_seed_file
from common.cli import add_json_flag, emit, parser


def main(argv: list[str] | None = None) -> int:
    top = parser("clinicdb", "Create and seed the clinic database.")
    commands = top.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the schema")
    seed = commands.add_parser("seed", help="load clinics, clinicians and patients from JSON")
    seed.add_argument("file")
    add_json_flag(seed)
    args = top.parse_args(argv)

    db = open_db(args.db)
    if args.command == "seed":
        counts = load_seed_file(db, args.file)
        emit(counts, args.json, ", ".join(f"{count} {name}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
