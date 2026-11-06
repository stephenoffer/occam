"""Application object and WSGI entry point."""

from __future__ import annotations

import logging
import time
import traceback
from collections import defaultdict, deque
from http import HTTPStatus
from urllib.parse import parse_qsl

from . import __version__, db
from .config import Settings, load_settings
from .http import HTTPError, Request, Response, RouteTable, Router, TooManyRequests, json_response
from .routes import customers, invoices, reports, subscriptions, webhooks
from .services.payments import GatewayClient, PaymentGateway

logger = logging.getLogger(__name__)

system_routes = RouteTable()


@system_routes.get("/healthz")
def healthz(request: Request) -> Response:
    request.conn.execute("SELECT 1").fetchone()
    return json_response({"status": "ok", "version": __version__})


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        bucket = self._hits[key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= self.per_minute:
            return False
        bucket.append(now)
        return True


class App:
    def __init__(self, settings: Settings | None = None, gateway: PaymentGateway | None = None) -> None:
        self.settings = settings or load_settings()
        self.settings.validate()
        self.gateway = gateway or GatewayClient(self.settings.gateway_url, self.settings.gateway_api_key)
        self.limiter = RateLimiter(self.settings.rate_limit_per_minute)
        self.router = Router()
        for module in (customers, subscriptions, invoices, webhooks, reports):
            self.router.include(module.routes)
        self.router.include(system_routes)
        conn = db.connect(self.settings.database_path)
        try:
            db.init_schema(conn)
            db.seed_plans(conn)
        finally:
            conn.close()

    def handle(self, request: Request) -> Response:
        conn = db.connect(self.settings.database_path)
        request.conn = conn
        request.app = self
        try:
            token = request.headers.get("authorization")
            if token and not self.limiter.allow(token):
                raise TooManyRequests("rate limit exceeded")
            return self.router.dispatch(request)
        except HTTPError as exc:
            conn.rollback()
            return json_response({"error": exc.code, "message": exc.message}, status=exc.status)
        except Exception as exc:
            conn.rollback()
            logger.exception("unhandled error on %s %s", request.method, request.path)
            payload = {"error": "internal_error"}
            if self.settings.debug:
                payload["detail"] = str(exc)
                payload["traceback"] = traceback.format_exc()
            return json_response(payload, status=500)
        finally:
            conn.close()

    def __call__(self, environ: dict, start_response) -> list[bytes]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        headers = {k[5:].replace("_", "-").lower(): v for k, v in environ.items() if k.startswith("HTTP_")}
        request = Request(
            method=environ["REQUEST_METHOD"],
            path=environ.get("PATH_INFO", "/"),
            query=dict(parse_qsl(environ.get("QUERY_STRING", ""))),
            headers=headers,
            body=environ["wsgi.input"].read(length) if length else b"",
        )
        response = self.handle(request)
        status = f"{response.status} {HTTPStatus(response.status).phrase}"
        start_response(status, list(response.headers.items()))
        return [response.body]


def create_app() -> App:
    logging.basicConfig(level=logging.INFO)
    return App()

