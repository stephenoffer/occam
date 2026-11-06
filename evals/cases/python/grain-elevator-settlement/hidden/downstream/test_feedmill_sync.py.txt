"""The feed mill team's tests, as they run them against each release."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from feedmill_sync import contract_bushels, price_or_none, settle_for_mill
from grainbank.settlement import FeedError, Ledger

YESTERDAY = datetime.now(timezone.utc) - timedelta(days=1)
ROW = {"id": "T-1", "member": "M-1", "commodity": "corn", "gross_lb": 56000, "tare_lb": 28000, "moisture": "15.0",
       "test_weight": "57", "foreign_material": "0.5", "weighed_on": YESTERDAY.date().isoformat()}


def test_price_is_none_when_the_feed_is_down():
    with patch("grainbank.settlement.board_price", side_effect=FeedError("down")):
        assert price_or_none("corn") is None


def test_contract_bushels_uses_payable_bushels():
    assert contract_bushels([ROW])["corn"] == Decimal("500.00")
    with patch("grainbank.settlement.net_bushels", return_value=Decimal("1.00")) as bushels:
        assert contract_bushels([ROW])["corn"] == Decimal("1.00")
    assert bushels.called


def test_pricing_sees_the_patched_bushels():
    with patch("grainbank.settlement.net_bushels", return_value=Decimal("2.00")):
        ledger = Ledger()
        settle_for_mill([ROW], ledger, Decimal("4.00"))
    assert ledger.entries[0].bushels == Decimal("2.00")


def test_stale_ticket_threshold_can_be_tightened():
    with patch("grainbank.settlement.STALE_TICKET_DAYS", 0), patch("grainbank.settlement.send_alert") as alert:
        settle_for_mill([ROW], Ledger(), Decimal("4.00"))
    alert.assert_called_once()


def test_nothing_failed_on_a_good_load():
    assert settle_for_mill([ROW], Ledger(), Decimal("4.00")) == (["T-1"], {})
