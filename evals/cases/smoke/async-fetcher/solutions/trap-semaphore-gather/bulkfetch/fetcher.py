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


async def _fetch_one(url, transport, semaphore, enrich):
    async with semaphore:
        try:
            body = await transport.get(url)
            return Result(url, body=body, digest=await asyncio.to_thread(enrich, body))
        except Exception as error:
            return Result(url, error=error)


async def fetch_all(urls, transport, *, max_concurrency=20, enrich=enrich_record):
    semaphore = asyncio.Semaphore(max_concurrency)
    return await asyncio.gather(*[_fetch_one(url, transport, semaphore, enrich) for url in urls])
