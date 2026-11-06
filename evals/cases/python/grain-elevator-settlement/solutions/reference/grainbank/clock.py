"""The time, from one place."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ticket_age_days(ticket: "Ticket") -> int:
    return (utcnow().date() - ticket.weighed_on).days
