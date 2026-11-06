import json
import urllib.error
import urllib.parse
import urllib.request


class VendorError(Exception):
    pass


def _urllib_transport(url, headers):
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class VendorClient:
    def __init__(self, base_url, token, transport=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport or _urllib_transport

    def get_json(self, path, params=None):
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        status, body = self.transport(url, {"Authorization": f"Bearer {self.token}"})
        if status != 200:
            raise VendorError(f"{path}: HTTP {status}")
        try:
            return json.loads(body)
        except ValueError as error:
            raise VendorError(f"{path}: invalid JSON") from error

    def fetch_page(self, path, cursor=None, limit=100):
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = self.get_json(path, params)
        try:
            return data["results"], data.get("next")
        except KeyError:
            return [], None

    def fetch_all(self, path):
        records, cursor = [], None
        while True:
            page, cursor = self.fetch_page(path, cursor)
            records.extend(page)
            if not cursor:
                return records
