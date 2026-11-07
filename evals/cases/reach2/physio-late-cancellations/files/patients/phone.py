"""UK phone numbers, normalised to E.164 so the SMS sender can use them as they are."""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\d+")


def normalise(raw: str) -> str:
    """``07700 900123`` -> ``+447700900123``. Raises ValueError for anything that isn't a UK number."""
    text = raw.strip()
    digits = "".join(_DIGITS.findall(text))
    if text.startswith("+"):
        if not digits.startswith("44"):
            raise ValueError(f"only UK numbers are supported: {raw!r}")
        national = digits[2:]
    elif digits.startswith("0044"):
        national = digits[4:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        raise ValueError(f"not a UK number: {raw!r}")
    national = national.lstrip("0")
    if len(national) != 10:
        raise ValueError(f"wrong length for a UK number: {raw!r}")
    return "+44" + national


def is_mobile(number: str) -> bool:
    """Only mobiles get text messages."""
    return normalise(number).startswith("+447")
