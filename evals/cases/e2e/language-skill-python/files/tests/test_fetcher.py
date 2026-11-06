import asyncio

from fetcher import fetch_all


def test_fetch_all():
    assert asyncio.run(fetch_all(["a"])) == ["a"]
