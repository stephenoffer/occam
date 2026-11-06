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


edit("grainbank/grading.py", """    gross = _quantize_bushels(Decimal(net_pounds(ticket)) / spec.pounds_per_bushel)
    # TODO: this rounds the shrink and the dock and then the result. Should round once, at the end.
    shrink = _quantize_bushels(gross * moisture_shrink_percent(ticket) / 100)
    dock = _quantize_bushels(gross * foreign_material_dock_percent(ticket) / 100)
    return _quantize_bushels(gross - shrink - dock)
""", """    gross = Decimal(net_pounds(ticket)) / spec.pounds_per_bushel
    shrink = gross * moisture_shrink_percent(ticket) / 100
    dock = gross * foreign_material_dock_percent(ticket) / 100
    return _quantize_bushels(gross - shrink - dock)
""")
EDITS
