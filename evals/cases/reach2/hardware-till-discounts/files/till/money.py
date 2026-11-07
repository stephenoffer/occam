"""Formatting pence for receipts and reports. Amounts are always whole pence (ADR 0001)."""


def fmt(pence: int) -> str:
    """12345 -> '123.45', -5 -> '-0.05'."""
    sign = "-" if pence < 0 else ""
    pence = abs(pence)
    return f"{sign}{pence // 100}.{pence % 100:02d}"


def parse(text: str) -> int:
    """'123.45' -> 12345. Accepts a whole number of pounds too ('20' -> 2000)."""
    text = text.strip().lstrip("£")
    negative = text.startswith("-")
    text = text.lstrip("-")
    pounds, _, pence = text.partition(".")
    if not pounds.isdigit() or (pence and (not pence.isdigit() or len(pence) > 2)):
        raise ValueError(f"not an amount: {text!r}")
    value = int(pounds) * 100 + int(pence.ljust(2, "0") or 0)
    return -value if negative else value
