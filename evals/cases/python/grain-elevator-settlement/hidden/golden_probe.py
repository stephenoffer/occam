"""Prints what the settlement engine computes, through its original import path, for comparison with the starter."""

import json
import re
from decimal import Decimal

import grainbank.settlement as s

BOARD = Decimal("4.3725")
ROW = {"id": "T-1", "member": "M-1", "commodity": "corn", "gross_lb": 60117, "tare_lb": 27233, "moisture": "17.3",
       "test_weight": "55.1", "foreign_material": "1.37", "weighed_on": "2026-11-04", "location": "east"}


def load(**overrides):
    return s.ticket_from_dict({**ROW, **overrides})


def error_of(call):
    try:
        call()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


out = {}
loads = {
    "wet": load(),
    "soy": load(commodity="soybeans", gross_lb=58211, moisture="14.15", test_weight="54", location="river"),
    "wheat": load(commodity="wheat", gross_lb=71013, moisture="13.5", test_weight="58", foreign_material="0.5", location="north"),
    "sample": load(foreign_material="3.2"),
    "light": load(test_weight="49.9"),
}
out["net_bushels"] = {name: str(s.net_bushels(t)) for name, t in loads.items()}
out["shrink"] = {name: str(s.moisture_shrink_percent(t)) for name, t in loads.items()}
out["dock"] = {name: str(s.foreign_material_dock_percent(t)) for name, t in loads.items()}
out["grades"] = {name: s.grade_ticket(t).value for name, t in loads.items()}
out["drying"] = {name: str(s.drying_charge(t)) for name, t in loads.items()}
out["basis"] = {place: str(s.basis_for(place)) for place in ("north", "river", "east")}
out["commodities"] = {code: spec.pounds_per_bushel for code, spec in s.COMMODITIES.items()}
out["grade_values"] = [grade.value for grade in s.Grade]
out["grade_discounts"] = {grade.value: str(discount) for grade, discount in s.GRADE_DISCOUNTS.items()}
out["tiers"] = [[str(a), str(b)] for a, b in s.Ledger.PATRONAGE_TIERS]
out["patronage"] = {str(v): str(s.patronage_rate(Decimal(v))) for v in ("0", "10000", "10000.01", "50000", "50000.01")}
out["hierarchy"] = {
    name: [base.__name__ for base in getattr(s, name).__mro__[1:-1] if base.__name__ != "BaseException"]
    for name in ("GrainbankError", "GradingError", "FeedError", "LedgerError", "CheckpointError")
}
out["settings"] = {name: repr(getattr(s, name)) for name in (
    "ACTIVE_SEASON", "DEFAULT_FEED_URL", "DEFAULT_ALERT_URL", "MAX_FEED_RETRIES", "FEED_BACKOFF_SECONDS",
    "FEED_TIMEOUT_SECONDS", "STALE_TICKET_DAYS", "DRYING_RATE_PER_POINT")}

ledger = s.Ledger()
ledger.post("M-2", Decimal("0"), Decimal("10000"), "opening")
ledger.post("M-3", Decimal("0"), Decimal("10000.01"), "opening")
ledger.post("M-4", Decimal("0"), Decimal("50000.01"), "opening")
out["priced"] = {
    member: s.price_ticket(load(member=member), ledger, BOARD).to_dict() for member in ("M-1", "M-2", "M-3", "M-4")
}
out["priced_loads"] = {name: s.price_ticket(t, ledger, BOARD).to_dict() for name, t in loads.items()}

ledger = s.Ledger()
ledger.post_settlement(load(id="T-1"), BOARD)
ledger.post_settlement(load(id="T-2", commodity="soybeans", moisture="13.0"), BOARD)
ledger.post_settlement(load(id="T-3", member="M-2"), BOARD)
ledger.reverse("T-3", "wrong member")
out["ledger"] = {
    "balance": {m: str(ledger.balance(m)) for m in ("M-1", "M-2")},
    "ytd": {m: str(ledger.ytd_bushels(m)) for m in ("M-1", "M-2")},
    "members": ledger.members(),
    "memos": [entry.memo for entry in ledger.entries],
    "dict_keys": sorted(ledger.entries[0].to_dict()),
}
out["statement"] = re.sub(r"Generated: \S+", "Generated: X", s.render_statement("M-1", ledger))
out["statement_filename"] = s.statement_filename("M-1")

out["refusals"] = {
    "commodity": error_of(lambda: s.net_bushels(load(commodity="rye"))),
    "weights": error_of(lambda: s.validate_ticket(load(gross_lb=100, tare_lb=200))),
    "moisture": error_of(lambda: s.validate_ticket(load(moisture="41"))),
    "location": error_of(lambda: s.basis_for("moon")),
    "twice": error_of(lambda: ledger.post_settlement(load(id="T-1"), BOARD)),
    "reverse_twice": error_of(lambda: ledger.reverse("T-3", "again")),
    "season": error_of(lambda: s.set_season("next year")),
}
print(json.dumps(out, indent=1, sort_keys=True))
