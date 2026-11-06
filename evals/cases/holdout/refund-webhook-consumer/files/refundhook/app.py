"""WSGI entry point for the provider's webhook."""

import json
import logging
from http import HTTPStatus

from refundhook.consumer import handle_delivery

log = logging.getLogger(__name__)


def create_app(gateway, mailer, db_path):
    def app(environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        try:
            payload = json.loads(environ["wsgi.input"].read(length))
            status = handle_delivery(payload, gateway, mailer, db_path)
        except Exception:
            log.exception("delivery failed")
            status = 500
        start_response(f"{status} {HTTPStatus(status).phrase}", [("Content-Length", "0")])
        return [b""]

    return app
