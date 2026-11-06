"""The active season, and where this package finds the outside world."""

import os
import re

ACTIVE_SEASON = "2026-fall"
DEFAULT_FEED_URL = "https://feeds.grainbank.invalid/board.json"
DEFAULT_ALERT_URL = "https://hooks.grainbank.invalid/settlement-alerts"
MAX_FEED_RETRIES = 3
FEED_BACKOFF_SECONDS = 2.0
FEED_TIMEOUT_SECONDS = 10
STALE_TICKET_DAYS = 10
SEASON_RE = re.compile(r"^\d{4}-(spring|fall)$")


def set_season(season: str) -> None:
    """Roll the co-op over to a new season. Statements and checkpoints written after this carry it."""
    global ACTIVE_SEASON
    if not SEASON_RE.match(season):
        raise ValueError(f"not a season: {season!r}")
    ACTIVE_SEASON = season


def season_label() -> str:
    year, half = ACTIVE_SEASON.split("-")
    return f"{half.capitalize()} {year}"


def feed_url() -> str:
    return os.environ.get("GRAINBANK_FEED_URL", DEFAULT_FEED_URL)


def alert_url() -> str:
    return os.environ.get("GRAINBANK_ALERT_URL", DEFAULT_ALERT_URL)
