"""Book an accepted quote with the carrier API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .errors import RETRYABLE_CARRIER_ERRORS, BookingFailed
from .models import Quote

logger = logging.getLogger(__name__)


class CarrierClient(Protocol):
    """The one call we use from the carrier API."""

    def submit(self, payload: dict[str, str]) -> dict[str, str]:
        """Send a booking and return the carrier's response."""
        ...


@dataclass(frozen=True)
class BookingReceipt:
    """Proof that a carrier accepted a booking."""

    shipment: str
    carrier_reference: str


def _payload(quote: Quote) -> dict[str, str]:
    return {"shipment": quote.shipment, "lane": quote.lane, "total": str(quote.total)}


def submit_booking(
    client: CarrierClient,
    quote: Quote,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> BookingReceipt:
    """Book a quote, retrying transient carrier failures, or raise BookingFailed."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.submit(_payload(quote))
        except RETRYABLE_CARRIER_ERRORS as exc:
            logger.warning("booking attempt %d of %d failed: %s", attempt, attempts, exc)
            last_error = exc
            sleep(2.0**attempt)
            continue
        if "reference" not in response:
            raise BookingFailed(f"carrier response for {quote.shipment} has no reference")
        return BookingReceipt(quote.shipment, response["reference"])
    raise BookingFailed(f"no booking for {quote.shipment} after {attempts} tries") from last_error
