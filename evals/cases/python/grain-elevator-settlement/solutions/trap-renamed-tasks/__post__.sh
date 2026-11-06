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


path = Path("grainbank/jobs.py")
text = path.read_text()
text = re.sub(r'@app\.task\(name="grainbank\.settlement\.\w+"\)', "@app.task", text)
text = text.replace('app.send_task("grainbank.settlement.send_statement", ', "app.send_task(send_statement.name, ")
path.write_text(text)
EDITS
