"""Closing the trading day.

Closing copies the day's journal into the outbox, unchanged, as the store's tape for head office.
The store PC's uploader sends whatever is in the outbox overnight and moves it to `outbox/sent/`.
A day can only be closed once; ringing more sales on a closed day is refused by the front end, not
here.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from till import journal
from till.settings import load_settings


class AlreadyClosed(RuntimeError):
    pass


def tape_path(data_dir: Path, store: str, day: date) -> Path:
    return Path(data_dir) / "outbox" / f"{store}-{day.isoformat()}.tape"


def close_day(data_dir: Path, day: date) -> Path:
    settings = load_settings(data_dir)
    source = journal.journal_path(data_dir, day)
    target = tape_path(data_dir, settings.store, day)
    sent = target.parent / "sent" / target.name
    if target.exists() or sent.exists():
        raise AlreadyClosed(f"{day.isoformat()} is already closed")
    # Read it first, so a journal the till can't read is caught here rather than overnight.
    journal.read_day(data_dir, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.copyfile(source, target)
    else:
        target.write_text("", encoding="utf-8")
    return target
