from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freightquote import build_quote, quoting
from freightquote.models import QuoteLine

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def test_quote_prices_every_line(card, pallet):
    quote = build_quote(pallet, "HFX-MTL-ROAD", card, Decimal("0.10"), NOW)
    assert [line.label for line in quote.lines] == ["base freight", "fuel"]
    assert quote.total == sum(line.amount for line in quote.lines)
    assert quote.total == Decimal("696.30")


def test_quote_is_valid_for_seven_days(card, pallet):
    quote = build_quote(pallet, "HFX-MTL-ROAD", card, Decimal("0"), NOW)
    assert quote.valid_until - quote.issued_at == timedelta(days=7)


def test_total_is_base_when_there_are_no_surcharges(card, pallet, monkeypatch):
    monkeypatch.setattr(quoting, "surcharges_for", lambda *args: [])
    quote = build_quote(pallet, "HFX-MTL-ROAD", card, Decimal("0.10"), NOW)
    assert quote.lines == (QuoteLine("base freight", Decimal("633.00")),)
    assert quote.total == Decimal("633.00")


def test_rail_quote_uses_rail_rates(card, pallet):
    quote = build_quote(pallet, "MTL-WPG-RAIL", card, Decimal("0"), NOW)
    assert quote.total == Decimal("549.00")
