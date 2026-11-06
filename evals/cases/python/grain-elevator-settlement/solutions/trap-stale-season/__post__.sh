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


edit("grainbank/settlement.py", """    @property
    def ACTIVE_SEASON(self):
        return settings.ACTIVE_SEASON

""", "")
edit("grainbank/settlement.py", """        if name == "ACTIVE_SEASON":
            settings.ACTIVE_SEASON = value
            return
""", "")
edit("grainbank/settlement.py", "from .taskapp import app  # noqa: F401\n", "from .settings import ACTIVE_SEASON  # noqa: F401\nfrom .taskapp import app  # noqa: F401\n")
EDITS
