import asyncio

from bulkfetch import fetch_all


class FakeTransport:
    async def get(self, url):
        await asyncio.sleep(0)
        if "bad" in url:
            raise ValueError(url)
        return url.encode()


def test_results_in_order():
    results = asyncio.run(fetch_all(["a", "b", "c"], FakeTransport(), enrich=lambda body: "x"))
    assert [result.url for result in results] == ["a", "b", "c"]


def test_failure_is_isolated():
    results = asyncio.run(fetch_all(["a", "bad", "c"], FakeTransport(), enrich=lambda body: "x"))
    assert results[1].error is not None
    assert results[2].body == b"c"
