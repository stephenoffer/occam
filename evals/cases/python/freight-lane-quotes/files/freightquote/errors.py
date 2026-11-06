"""Exceptions raised by the quoting pipeline, and the error groups its adapters handle."""

from __future__ import annotations


class QuoteError(Exception):
    """Base class for failures the ops desk can act on."""


class RateCardError(QuoteError):
    """The published rate card is missing, unreadable or inconsistent."""


class IneligibleShipment(QuoteError):
    """No quote can be offered because the lane cannot carry the shipment."""


class BookingFailed(QuoteError):
    """The carrier did not accept a booking after every attempt."""


# What a carrier API call can raise when the failure is worth another attempt.
RETRYABLE_CARRIER_ERRORS: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)

# What reading a weekly fuel index can raise: a missing file, bad JSON, a malformed entry.
FEED_READ_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, LookupError, Exception)
