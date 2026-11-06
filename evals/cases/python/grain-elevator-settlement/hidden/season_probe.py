"""Rolling the season over has to be visible through the old path, and to everything that reads it."""

import grainbank.settlement as s

assert s.ACTIVE_SEASON == "2026-fall", s.ACTIVE_SEASON
s.set_season("2027-spring")
assert s.ACTIVE_SEASON == "2027-spring", f"old path still says {s.ACTIVE_SEASON}"
assert s.statement_filename("M-1") == "2027-spring-M-1.txt", s.statement_filename("M-1")
assert s.season_label() == "Spring 2027", s.season_label()
assert s.SettlementCheckpoint([]).season == "2027-spring"
assert s.build_statement("M-1", s.Ledger()).season == "Spring 2027"
print("ok")
