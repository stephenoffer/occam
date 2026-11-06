"""In-process copy of the vendor's sandbox API, supplied by the vendor for integration work.

Generated from their OpenAPI document. Do not edit: changes here would no longer reflect the vendor.
"""

import base64
import json
import urllib.parse

DATA = {
    "/v2/contacts": ("results", [{"id": f"contact-{n}", "email": f"c{n}@example.invalid"} for n in range(340)]),
    "/v2/companies": ("results", [{"id": f"company-{n}", "name": f"Company {n}"} for n in range(120)]),
    "/v2/deals": ("items", [{"id": f"deal-{n}", "amount": n * 10} for n in range(57)]),
}
MAX_LIMIT = 100


def _token(offset):
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _offset(token):
    return json.loads(base64.urlsafe_b64decode(token))["o"]


def respond(path, query):
    if path not in DATA:
        return 404, {"error": "unknown endpoint"}
    key, rows = DATA[path]
    limit = min(int(query.get("limit", [MAX_LIMIT])[0]), MAX_LIMIT)
    start = _offset(query["pageToken"][0]) if "pageToken" in query else 0
    page = {key: rows[start:start + limit]}
    if start + limit < len(rows):
        page["nextPageToken"] = _token(start + limit)
    return 200, page


def transport(url, headers):
    if not headers.get("Authorization", "").startswith("Bearer "):
        return 401, b'{"error": "unauthorized"}'
    parsed = urllib.parse.urlsplit(url)
    status, payload = respond(parsed.path, urllib.parse.parse_qs(parsed.query))
    return status, json.dumps(payload).encode()
