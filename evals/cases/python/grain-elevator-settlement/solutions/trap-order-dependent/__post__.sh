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


edit("grainbank/pricing.py", "from .board import board_price\n", "from .board import board_price\nfrom .ledger import Ledger\n")
edit("grainbank/pricing.py", "    for threshold, rate in PATRONAGE_TIERS:", "    for threshold, rate in Ledger.PATRONAGE_TIERS:")
edit("grainbank/ledger.py", "from .pricing import PATRONAGE_TIERS, PricedTicket, price_ticket\n", "from . import pricing\n")
edit("grainbank/ledger.py", "    PATRONAGE_TIERS = PATRONAGE_TIERS\n", """    PATRONAGE_TIERS = (
        (Decimal("50000"), Decimal("0.06")),
        (Decimal("10000"), Decimal("0.03")),
    )
""")
edit("grainbank/ledger.py", "priced = price_ticket(ticket, self, board)", "priced = pricing.price_ticket(ticket, self, board)")
edit("grainbank/ledger.py", "-> PricedTicket:", '-> "pricing.PricedTicket":')
edit("grainbank/settlement.py", "from . import alerts, board,", "from . import pricing  # noqa: F811, has to come before the ledger\nfrom . import alerts, board,")
path = Path("grainbank/pricing.py")
text = path.read_text()
text = re.sub(r'# Bushels already delivered this year.*?\n\)\n', "", text, flags=re.S)
path.write_text(text)
edit("grainbank/settlement.py", "    PATRONAGE_TIERS,\n", "")
EDITS
