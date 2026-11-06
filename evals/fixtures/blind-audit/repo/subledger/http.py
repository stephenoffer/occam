"""A small request/response layer and router, so the service needs no web framework."""

from __future__ import annotations

import functools
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    import orjson
except ImportError:
    orjson = None


class HTTPError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message or self.code


class BadRequest(HTTPError):
    status, code = 400, "bad_request"


class Unauthorized(HTTPError):
    status, code = 401, "unauthorized"


class Forbidden(HTTPError):
    status, code = 403, "forbidden"


class NotFound(HTTPError):
    status, code = 404, "not_found"


class Conflict(HTTPError):
    status, code = 409, "conflict"


class TooManyRequests(HTTPError):
    status, code = 429, "rate_limited"


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    params: dict[str, str] = field(default_factory=dict)
    conn: Any = None
    app: Any = None
    tenant_id: int | None = None
    role: str | None = None

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            payload = json.loads(self.body)
        except ValueError as exc:
            raise BadRequest("request body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise BadRequest("request body must be a JSON object")
        return payload

    def query_int(self, name: str, default: int) -> int:
        raw = self.query.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise BadRequest(f"{name} must be an integer") from exc

    def param_int(self, name: str) -> int:
        try:
            return int(self.params[name])
        except (KeyError, ValueError) as exc:
            raise NotFound() from exc


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.body)


def json_response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    body = orjson.dumps(payload) if orjson else json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", "ETag": etag_for(body)}
    merged.update(headers or {})
    return Response(status=status, body=body, headers=merged)


def etag_for(body: bytes) -> str:
    return '"' + hashlib.md5(body, usedforsecurity=False).hexdigest() + '"'


Handler = Callable[[Request], Response]


class RouteTable:
    """Collects routes at import time. Each routes module owns one of these."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, Handler]] = []

    def add(self, method: str, pattern: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.entries.append((method, pattern, handler))
            return handler

        return decorator

    get = functools.partialmethod(add, "GET")
    post = functools.partialmethod(add, "POST")
    put = functools.partialmethod(add, "PUT")
    patch = functools.partialmethod(add, "PATCH")
    delete = functools.partialmethod(add, "DELETE")


class Router:
    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def include(self, table: RouteTable) -> None:
        for method, pattern, handler in table.entries:
            regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
            self._routes.append((method, re.compile(regex), handler))

    def dispatch(self, request: Request) -> Response:
        path_matched = False
        for method, regex, handler in self._routes:
            match = regex.fullmatch(request.path)
            if match is None:
                continue
            path_matched = True
            if method == request.method:
                request.params = match.groupdict()
                return handler(request)
        if path_matched:
            return json_response({"error": "method_not_allowed"}, status=405)
        raise NotFound(f"no route for {request.path}")
