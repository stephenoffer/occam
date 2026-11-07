"""Finding tapes in the inbox.

The upload service drops tapes into the inbox as they arrive overnight. Late tapes (a store that
was offline) arrive in later nights, so takings for a day are always worked out from whatever is in
the inbox for that day, never from what arrived on a given night.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path


def tapes_for_day(inbox: Path, day: date) -> list[Path]:
    inbox = Path(inbox)
    found = sorted(inbox.glob(f"*-{day.isoformat()}.tape"))
    archived = inbox / "archive" / day.strftime("%Y-%m")
    if archived.is_dir():
        seen = {path.name for path in found}
        found += sorted(p for p in archived.glob(f"*-{day.isoformat()}.tape") if p.name not in seen)
    return found


def stores_reporting(inbox: Path, day: date) -> list[str]:
    return sorted({path.name.rsplit("-", 3)[0] for path in tapes_for_day(inbox, day)})
