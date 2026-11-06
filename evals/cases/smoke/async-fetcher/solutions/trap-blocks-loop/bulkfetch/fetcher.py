import asyncio
import hashlib
from dataclasses import dataclass


@dataclass
class Result:
    url: str
    body: bytes | None = None
    digest: str | None = None
    error: Exception | None = None


def enrich_record(body):
    """Content fingerprint used downstream. Deliberately expensive."""
    return hashlib.pbkdf2_hmac("sha256", body, b"bulkfetch", 200_000).hex()


async def _fetch_one(url, transport, enrich):
    try:
        body = await transport.get(url)
        return Result(url, body=body, digest=enrich(body))
    except Exception as error:
        return Result(url, error=error)


async def fetch_all(urls, transport, *, max_concurrency=20, enrich=enrich_record):
    source = enumerate(urls)
    results = {}

    async def worker():
        for index, url in source:
            results[index] = await _fetch_one(url, transport, enrich)

    workers = [asyncio.create_task(worker()) for _ in range(max_concurrency)]
    try:
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    return [results[index] for index in sorted(results)]
