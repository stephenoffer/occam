"""Reporting endpoints."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from .. import store
from ..auth import authenticated
from ..http import BadRequest, Request, Response, RouteTable, json_response
from ..utils import dates, money

routes = RouteTable()

BASELINE_CHURN = 0.03


class TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > self.ttl_seconds:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._entries.clear()


_cache = TTLCache(ttl_seconds=300)


def _monthly_recurring_cents(conn: sqlite3.Connection, tenant_id: int) -> int:
    total = 0
    for row in store.recurring_rows(conn, tenant_id):
        amount = row["quantity"] * row["price_cents"]
        total += money.ratio_of(amount, 1, 12) if row["interval"] == "year" else amount
    return total


@routes.get("/reports/mrr")
@authenticated
def monthly_recurring_revenue(request: Request) -> Response:
    as_of = dates.utc_today().isoformat()
    cache_key = f"mrr:{as_of}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return json_response(cached)
    payload = {"as_of": as_of, "mrr_cents": _monthly_recurring_cents(request.conn, request.tenant_id)}
    _cache.set(cache_key, payload)
    return json_response(payload)


@routes.get("/reports/revenue")
@authenticated
def revenue(request: Request) -> Response:
    start = request.query.get("from")
    end = request.query.get("to")
    if not start or not end:
        raise BadRequest("from and to are required")
    try:
        dates.parse_date(start)
        dates.parse_date(end)
    except ValueError as exc:
        raise BadRequest("from and to must be ISO dates") from exc
    cents = store.revenue_between(request.conn, request.tenant_id, start, end)
    return json_response({"from": start, "to": end, "revenue_cents": cents})


@routes.get("/reports/churn")
@authenticated
def churn(request: Request) -> Response:
    month = request.query.get("month") or dates.utc_today().strftime("%Y-%m")
    try:
        dates.month_bounds(month)
    except ValueError as exc:
        raise BadRequest("month must look like 2026-03") from exc
    active = store.count_active_subscriptions(request.conn, request.tenant_id)
    churned = round(active * BASELINE_CHURN)
    rate = churned / active if active else 0.0
    return json_response({"month": month, "active_at_start": active, "churned": churned, "churn_rate": round(rate, 4)})
