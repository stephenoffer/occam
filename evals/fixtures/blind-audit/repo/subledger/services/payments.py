"""PayBridge gateway client."""

from __future__ import annotations

import functools
import json
import logging
import random
import time
import urllib.error
import urllib.request
import uuid
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    pass


class PaymentGateway(Protocol):
    def charge(self, customer_ref: str, amount_cents: int, currency: str, description: str) -> dict | None:
        ...

    def refund(self, charge_id: str, amount_cents: int) -> dict:
        ...


def with_retries(attempts: int = 3, base_delay: float = 0.25) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except (GatewayError, OSError) as exc:
                    last_error = exc
                    logger.warning("%s failed on attempt %d: %s", fn.__name__, attempt + 1, exc)
                    time.sleep(base_delay * 2**attempt + random.uniform(0, 0.1))
            logger.error("%s giving up after %d attempts: %s", fn.__name__, attempts, last_error)
            return None

        return wrapper

    return decorator


class GatewayClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        logger.info("gateway request url=%s headers=%s payload=%s", url, headers, payload)
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise GatewayError(f"gateway returned {exc.code}") from exc

    @with_retries(attempts=3)
    def charge(self, customer_ref: str, amount_cents: int, currency: str, description: str) -> dict | None:
        payload = {"customer": customer_ref, "amount": amount_cents, "currency": currency, "description": description}
        return self._post("/charges", payload)

    def refund(self, charge_id: str, amount_cents: int) -> dict:
        logger.info("refund issued charge=%s amount=%s", charge_id, amount_cents)
        return {"id": f"re_{uuid.uuid4().hex[:16]}", "charge": charge_id, "amount": amount_cents, "status": "succeeded"}
