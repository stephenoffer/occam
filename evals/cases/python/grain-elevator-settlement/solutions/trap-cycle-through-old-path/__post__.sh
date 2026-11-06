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

LOOKUPS = {'alerts': ['utcnow', 'urlopen'], 'board': ['urlopen', 'send_alert'], 'pricing': ['board_price', 'net_bushels'], 'ledger': ['utcnow', 'price_ticket'], 'statements': ['utcnow'], 'checkpoints': ['utcnow', 'settle_ticket'], 'settling': ['send_alert', 'ticket_age_days', 'settle_ticket'], 'clock': ['utcnow'], 'jobs': ['send_alert']}
CONSTANTS = {'board': ['MAX_FEED_RETRIES', 'FEED_BACKOFF_SECONDS'], 'settling': ['STALE_TICKET_DAYS']}
HELPER = """

def _old():
    from . import settlement  # inside a function, because settlement imports this module

    return settlement

"""
for module, names in LOOKUPS.items():
    path = Path(f"grainbank/{module}.py")
    lines = path.read_text().split("\n")
    for index, line in enumerate(lines):
        if line.startswith(("from ", "import ")) or line.lstrip().startswith("def "):
            continue
        for name in names:
            line = re.sub(r"(?<![\w.])" + name + r"(?=\()", "_old()." + name, line)
        for name in CONSTANTS.get(module, []):
            line = re.sub(r"(?<![\w.])" + name + r"\b", "_old()." + name, line)
        lines[index] = line
    text = "\n".join(lines)
    match = list(re.finditer(r"^(?:from|import) .*(?:\(\n(?:.*\n)*?\))?$", text, re.M))[-1]
    path.write_text(text[:match.end()] + "\n" + HELPER + text[match.end():])
EDITS
