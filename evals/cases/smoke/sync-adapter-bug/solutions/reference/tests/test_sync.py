import json

from crmsync import db, sync
from crmsync.client import VendorClient


def mock_transport(pages):
    calls = iter(pages)

    def transport(url, headers):
        return 200, json.dumps(next(calls)).encode()

    return transport


def test_fetch_all_follows_pages():
    client = VendorClient("https://x.invalid", "t", transport=mock_transport([
        {"results": [{"id": "1"}], "nextPageToken": "abc"},
        {"results": [{"id": "2"}]},
    ]))
    assert [row["id"] for row in client.fetch_all("/v2/contacts")] == ["1", "2"]


def test_sync_all_counts(tmp_path):
    client = VendorClient("https://x.invalid", "t", transport=mock_transport([
        {"results": [{"id": "1"}]},
        {"results": [{"id": "2"}]},
        {"items": [{"id": "3"}]},
    ]))
    connection = db.connect(str(tmp_path / "t.db"))
    assert sync.sync_all(client, connection) == {"contacts": 1, "companies": 1, "deals": 1}
