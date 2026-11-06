"""The published freight tariff, in US dollars per tonne."""

from decimal import Decimal
from typing import Final

from tidewater.core.errors import DocumentError

USD_PER_TONNE: Final = {
    "SIN-RTM": Decimal("182.50"),
    "SIN-LAX": Decimal("211.00"),
    "RTM-NYC": Decimal("96.75"),
    "HAM-NYC": Decimal("101.20"),
    "YOK-SIN": Decimal("74.30"),
}


def base_freight_usd(lane: str, tonnes: Decimal) -> Decimal:
    try:
        return USD_PER_TONNE[lane] * tonnes
    except KeyError:
        raise DocumentError(f"no tariff for lane {lane}") from None
