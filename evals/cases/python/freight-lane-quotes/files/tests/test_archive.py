from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freightquote import Quote
from freightquote.archive import archive_quote, quoted_totals

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def quote(total, issued_at):
    return Quote("S-1", "R1", (), Decimal(total), issued_at, issued_at + timedelta(days=7))


def test_totals_come_back_oldest_first(tmp_path):
    path = tmp_path / "quotes.db"
    archive_quote(path, quote("200.00", NOW + timedelta(hours=1)))
    archive_quote(path, quote("100.00", NOW))
    assert quoted_totals(path, "S-1") == [Decimal("100.00"), Decimal("200.00")]


def test_unknown_shipment_has_no_totals(tmp_path):
    path = tmp_path / "quotes.db"
    archive_quote(path, quote("100.00", NOW))
    assert quoted_totals(path, "S-2") == []
