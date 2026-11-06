#!/usr/bin/env bash
set -eu
cp -R "$(dirname "$0")/../reference/grainbank/." grainbank/
python3 - <<'EDITS'
from pathlib import Path
import re

def edit(name, old, new):
    path = Path(name)
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


edit("grainbank/checkpoints.py", "from .settling import settle_ticket\n", "")
edit("grainbank/checkpoints.py", '        settled = []\n        for ticket in self.remaining():', '        from .jobs import settle_ticket  # inside a function, because jobs imports this module\n\n        settled = []\n        for ticket in self.remaining():')
edit("grainbank/jobs.py", "from .settling import settle_batch\n", "from .settling import settle_batch, settle_ticket  # noqa: F401\n")
EDITS
