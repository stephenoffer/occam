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


path = Path("grainbank/settlement.py")
text = path.read_text()
start = text.index("_HOMES = (")
path.write_text(text[:start] + """
def __getattr__(name):
    if name == "ACTIVE_SEASON":
        return settings.ACTIVE_SEASON
    raise AttributeError(name)
""")
EDITS
