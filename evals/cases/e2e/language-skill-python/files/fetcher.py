import asyncio


async def fetch(url):
    await asyncio.sleep(0.01)
    return url


async def _one(url):
    try:
        return await fetch(url)
    except asyncio.CancelledError:
        return None


async def fetch_all(urls):
    return await asyncio.gather(*[_one(u) for u in urls])
