def format_price(cents):
    """A price for display, in US dollars."""
    return f"${cents // 100}.{cents % 100:02d}"
