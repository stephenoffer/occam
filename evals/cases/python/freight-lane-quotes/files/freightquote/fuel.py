"""The carriers' weekly fuel index."""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from .codec import decode
from .errors import FEED_READ_ERRORS

logger = logging.getLogger(__name__)


def read_fuel_rate(path: Path) -> Decimal:
    """Return the latest published fuel surcharge rate, as a fraction of base freight."""
    try:
        weeks = decode(path.read_text(encoding="utf-8"))["weeks"]
        latest = max(weeks, key=lambda week: week["published"])
        return Decimal(latest["rate"])
    except FEED_READ_ERRORS as exc:
        logger.debug("fuel index not available: %s", exc)
        return Decimal("0")
