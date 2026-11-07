CURRENCIES = {"USD": ("$", 2), "EUR": ("\u20ac", 2), "GBP": ("\u00a3", 2), "JPY": ("\u00a5", 0)}


def format_price(minor_units, currency):
    """A price for display, from an amount in the currency's minor units. See the README's table."""
    if currency not in CURRENCIES:
        raise ValueError(f"unknown currency {currency!r}")
    symbol, digits = CURRENCIES[currency]
    if digits == 0:
        return f"{symbol}{minor_units}"
    scale = 10 ** digits
    return f"{symbol}{minor_units // scale}.{minor_units % scale:0{digits}d}"
