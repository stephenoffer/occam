"""PayGate refunds API client. Vendored from paygate-sdk 3.2."""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request


class GatewayError(Exception):
    """Base class for PayGate client errors."""


class GatewayUnavailable(GatewayError):
    """The request did not reach PayGate. Nothing was processed."""


class GatewayTimeout(GatewayError):
    """The request was sent but no response arrived in time. PayGate may have processed it."""


class PayGateClient:
    def __init__(self, api_key, base_url="https://api.paygate.invalid/v1", timeout=5.0):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout

    def create_refund(self, order_id, amount_cents, idempotency_key=None):
        """Create a refund and return its id. Money moves as soon as PayGate commits it.

        idempotency_key is an optional client-chosen string. PayGate keeps one refund
        per key: repeating a key returns the id of the refund already created under it.
        """
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        body = {"order_id": order_id, "amount_cents": amount_cents}
        return self._request("POST", "/refunds", body, headers)["id"]

    def list_refunds(self, order_id):
        """Return the order's refunds as dicts: id, order_id, amount_cents, idempotency_key."""
        query = urllib.parse.urlencode({"order_id": order_id})
        return self._request("GET", f"/refunds?{query}")["refunds"]

    def _request(self, method, path, body=None, headers=None):
        request = urllib.request.Request(
            self._base_url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except TimeoutError as exc:
            raise GatewayTimeout(str(exc)) from exc
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503):
                raise GatewayUnavailable(f"HTTP {exc.code}") from exc
            raise GatewayError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, socket.gaierror) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise GatewayTimeout(str(exc)) from exc
            raise GatewayUnavailable(str(exc)) from exc
