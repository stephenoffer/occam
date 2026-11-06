"""Plain text rendering of a quote for the ops desk's email template."""

from __future__ import annotations

from .models import Quote

LABEL_WIDTH = 28
AMOUNT_WIDTH = 12


def render_quote(quote: Quote, tz_name: str = "UTC") -> str:
    """Render a quote as an aligned text block, with its expiry in the given timezone."""
    from zoneinfo import ZoneInfo

    expires = quote.valid_until.astimezone(ZoneInfo(tz_name))
    rows = [f"Quote for {quote.shipment} on {quote.lane}"]
    rows += [f"{line.label:<{LABEL_WIDTH}}{line.amount:>{AMOUNT_WIDTH}}" for line in quote.lines]
    rows.append(f"{'total':<{LABEL_WIDTH}}{quote.total:>{AMOUNT_WIDTH}}")
    rows.append(f"valid until {expires:%Y-%m-%d %H:%M %Z}")
    return "\n".join(rows)
