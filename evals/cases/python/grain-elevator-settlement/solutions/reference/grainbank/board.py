"""Board prices from the feed, and the cache of them."""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from urllib.error import URLError
from urllib.request import urlopen

from .alerts import send_alert
from .errors import FeedError
from .settings import FEED_BACKOFF_SECONDS, FEED_TIMEOUT_SECONDS, MAX_FEED_RETRIES, feed_url

log = logging.getLogger("grainbank.settlement")

_PRICE_CACHE: dict[str, Decimal] = {}


def fetch_board() -> dict[str, Decimal]:
    """Fetch today's board prices, retrying, and raise an alert if the feed stays down."""
    last_error = None
    for attempt in range(MAX_FEED_RETRIES):
        try:
            with urlopen(feed_url(), timeout=FEED_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode())
            return {code: Decimal(str(price)) for code, price in payload["prices"].items()}
        except (URLError, ValueError, KeyError) as exc:
            last_error = exc
            log.warning("board feed attempt %d failed: %s", attempt + 1, exc)
            if attempt + 1 < MAX_FEED_RETRIES:
                time.sleep(FEED_BACKOFF_SECONDS * (attempt + 1))
    send_alert("board feed down", str(last_error))
    raise FeedError(f"board feed down after {MAX_FEED_RETRIES} attempts: {last_error}")


def board_price(commodity: str) -> Decimal:
    if commodity not in _PRICE_CACHE:
        _PRICE_CACHE.update(fetch_board())
    try:
        return _PRICE_CACHE[commodity]
    except KeyError:
        raise FeedError(f"the board has no price for {commodity}") from None


def clear_price_cache() -> None:
    _PRICE_CACHE.clear()
