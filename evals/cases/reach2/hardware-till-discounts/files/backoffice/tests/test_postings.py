from datetime import date

from backoffice.nominal import postings, to_csv
from backoffice.takings import takings_for_day
from tape_helpers import copy_fixtures

DAY = date(2026, 10, 5)


def test_postings_balance(tmp_path):
    takings = takings_for_day(copy_fixtures(tmp_path / "inbox"), DAY)
    for store_takings in takings.values():
        assert sum(amount for *_, amount in postings(store_takings)) == 0


def test_csv(tmp_path):
    takings = takings_for_day(copy_fixtures(tmp_path / "inbox"), DAY)
    lines = to_csv([takings["BRH05"]]).splitlines()
    assert lines == [
        "account,store,reference,amount",
        "4040,BRH05,2026-10-05 GDN,-27.96",
        "4030,BRH05,2026-10-05 TLS,-16.50",
        "1200,BRH05,2026-10-05 cash,27.96",
        "1210,BRH05,2026-10-05 card,16.50",
    ]
