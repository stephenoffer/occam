from datetime import UTC, datetime
from decimal import Decimal

from freightquote import Quote, QuoteLine
from freightquote.formatting import render_quote

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def quote():
    lines = (QuoteLine("base freight", Decimal("100.00")), QuoteLine("fuel", Decimal("12.00")))
    return Quote("S-1", "R1", lines, Decimal("112.00"), NOW, NOW)


def test_total_is_on_its_own_row():
    assert "total" in render_quote(quote()).splitlines()[3]
    assert "112.00" in render_quote(quote()).splitlines()[3]


def test_expiry_uses_the_requested_timezone():
    assert "2026-11-05 08:00 AST" in render_quote(quote(), "America/Halifax")
