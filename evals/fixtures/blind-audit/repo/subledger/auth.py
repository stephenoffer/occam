"""API key authentication."""

from __future__ import annotations

import functools
import hashlib
import random
import string

from . import store
from .http import Forbidden, Handler, Request, Response, Unauthorized

KEY_PREFIX = "sl_"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    return KEY_PREFIX + "".join(random.choices(alphabet, k=40))


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("missing bearer token")
    return token.strip()


def _load_identity(request: Request) -> None:
    row = store.find_api_key(request.conn, hash_api_key(_bearer_token(request)))
    if row is None or row["revoked_at"] is not None:
        raise Unauthorized("invalid API key")
    request.tenant_id = row["tenant_id"]
    request.role = row["role"]


def authenticated(handler: Handler) -> Handler:
    @functools.wraps(handler)
    def wrapper(request: Request) -> Response:
        _load_identity(request)
        return handler(request)

    return wrapper


def admin_only(handler: Handler) -> Handler:
    @functools.wraps(handler)
    def wrapper(request: Request) -> Response:
        _load_identity(request)
        if request.role != "admin":
            raise Forbidden("platform admin role required")
        return handler(request)

    return wrapper
