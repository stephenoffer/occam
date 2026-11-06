"""Patches on the old path reach the code that uses the name, and go away again when the patch ends."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import grainbank.settlement as s

FROZEN = datetime(2031, 1, 2, 3, 4, tzinfo=timezone.utc)
ROW = {"id": "T-1", "member": "M-1", "commodity": "corn", "gross_lb": 56000, "tare_lb": 28000, "moisture": "15.0",
       "test_weight": "57", "foreign_material": "0.5", "weighed_on": "2030-12-30"}
ticket = s.ticket_from_dict(ROW)
real_utcnow = s.utcnow

# A patch on the clock reaches every reader of the clock, in either spelling of patch.
for patcher in (patch("grainbank.settlement.utcnow", return_value=FROZEN), patch.object(s, "utcnow", return_value=FROZEN)):
    with patcher:
        assert s.Ledger().post("M-1", Decimal("1")).posted_at == FROZEN, "Ledger.post"
        assert s.ticket_age_days(ticket) == 3, "ticket_age_days"
        assert s.build_statement("M-1", s.Ledger()).generated_on == FROZEN.date(), "build_statement"
    assert s.utcnow is real_utcnow, "the patch was not undone on the old path"
    assert s.Ledger().post("M-1", Decimal("1")).posted_at != FROZEN, "the patch was not undone where the code lives"

# A nested patch unwinds in order.
later = datetime(2032, 1, 1, tzinfo=timezone.utc)
with patch("grainbank.settlement.utcnow", return_value=FROZEN):
    with patch("grainbank.settlement.utcnow", return_value=later):
        assert s.Ledger().post("M-1", Decimal("1")).posted_at == later, "inner patch"
    assert s.Ledger().post("M-1", Decimal("1")).posted_at == FROZEN, "outer patch"

# The transport.
with patch("grainbank.settlement.urlopen", side_effect=URLError("down")) as opened, patch(
    "grainbank.settlement.time.sleep"
), patch("grainbank.settlement.send_alert") as alert:
    try:
        s.fetch_board()
    except s.FeedError:
        pass
    else:
        raise AssertionError("fetch_board should have failed")
    assert opened.call_count == 3, "fetch_board goes through urlopen"
    assert alert.call_count == 1, "fetch_board goes through send_alert"

# Constants and collaborators.
with patch("grainbank.settlement.urlopen", side_effect=URLError("down")) as opened, patch(
    "grainbank.settlement.MAX_FEED_RETRIES", 2
), patch("grainbank.settlement.FEED_BACKOFF_SECONDS", 0), patch("grainbank.settlement.send_alert"):
    try:
        s.fetch_board()
    except s.FeedError:
        pass
    assert opened.call_count == 2, "MAX_FEED_RETRIES"

with patch("grainbank.settlement.send_alert") as alert, patch("grainbank.settlement.utcnow", return_value=FROZEN), patch(
    "grainbank.settlement.STALE_TICKET_DAYS", 1
):
    s.settle_ticket(ticket, s.Ledger(), Decimal("4"))
    assert alert.call_count == 1, "settle_ticket reads STALE_TICKET_DAYS and calls send_alert"

with patch("grainbank.settlement.settle_ticket", side_effect=s.LedgerError("no")) as settle:
    settled, failures = s.settle_batch([ticket], s.Ledger(), Decimal("4"))
    assert (settled, list(failures)) == ([], ["T-1"]), "settle_batch goes through settle_ticket"
    assert settle.called

with patch("grainbank.settlement.board_price", return_value=Decimal("9")) as board:
    assert s.price_ticket(ticket, s.Ledger()).board == Decimal("9"), "price_ticket goes through board_price"
    assert board.called

priced = MagicMock(amount=Decimal("3"), bushels=Decimal("1"), commodity="corn", grade=s.Grade.NO1)
with patch("grainbank.settlement.price_ticket", return_value=priced) as price:
    ledger = s.Ledger()
    ledger.post_settlement(ticket)
    assert ledger.balance("M-1") == Decimal("3"), "post_settlement goes through price_ticket"
    assert price.called

with patch("grainbank.settlement.net_bushels", return_value=Decimal("2")):
    assert s.price_ticket(ticket, s.Ledger(), Decimal("4")).bushels == Decimal("2"), "price_ticket goes through net_bushels"

with patch("grainbank.settlement.Ledger.post") as post:
    s.Ledger().post_settlement(ticket, Decimal("4"))
    assert post.called, "class attribute"

with patch.dict("grainbank.settlement._PRICE_CACHE", {"barley": Decimal("7")}, clear=True):
    assert s.board_price("barley") == Decimal("7"), "the price cache at the old path is the one in use"

print("ok")
