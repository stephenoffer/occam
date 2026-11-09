#!/usr/bin/env python3
"""Record or verify hashes of every eval case file, so cases cannot quietly move after results exist.

    freeze.py write    # at the freeze
    freeze.py check    # also run by tests/test_scenarios.py
"""

import hashlib
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent
RECORD = EVALS / "FROZEN.sha256"
MAY_BE_WITHHELD = {"hard", "large"}  # large holds a copy of a third-party repository, kept out of the published one


def current() -> dict[str, str]:
    files = (p for p in (EVALS / "cases").rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {str(p.relative_to(EVALS)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def differences() -> list[str]:
    recorded = dict(reversed(line.split("  ", 1)) for line in RECORD.read_text().splitlines())
    now = current()
    # A suite in a blind round stays out of the published repository until its runs are done, which says nothing about its files.
    withheld = {suite for suite in MAY_BE_WITHHELD if not (EVALS / "cases" / suite).is_dir()}
    recorded = {name: digest for name, digest in recorded.items() if name.split("/")[1] not in withheld}
    return sorted(name for name in recorded.keys() | now.keys() if recorded.get(name) != now.get(name))


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        RECORD.write_text("".join(f"{digest}  {name}\n" for name, digest in current().items()))
        print(f"froze {len(current())} files")
    else:
        changed = differences()
        print("\n".join(changed) or "no changes since the freeze")
        raise SystemExit(1 if changed else 0)
