class AsyncFleetClient:
    """The fleet API, through any transport with an async get(path, params) -> dict."""

    def __init__(self, transport):
        self._transport = transport

    async def list_vehicles(self, page_size=50):
        first = await self._transport.get("/vehicles", {"page": 1, "size": page_size})
        vehicles = list(first["items"])
        pages = -(-first["total"] // page_size)
        for page in range(2, pages + 1):
            vehicles += (await self._transport.get("/vehicles", {"page": page, "size": page_size}))["items"]
        return vehicles
