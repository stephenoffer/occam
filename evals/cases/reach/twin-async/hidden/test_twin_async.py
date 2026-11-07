import importlib
import sys

import pytest


@pytest.fixture
def load(ws):
    """Import modules from the finished workspace, fresh for each test."""
    tops = {path.stem for path in ws.iterdir() if (path / "__init__.py").exists() or path.suffix == ".py"} - {"conftest", "tests"}
    for key in [key for key in sys.modules if key.split(".")[0] in tops]:
        del sys.modules[key]
    sys.path.insert(0, str(ws))
    yield importlib.import_module
    sys.path.remove(str(ws))


import asyncio


class Transport:
    def __init__(self, total):
        self.vehicles = [{"id": n} for n in range(total)]

    def get(self, path, params):
        start = (params["page"] - 1) * params["size"]
        return {"total": len(self.vehicles), "items": self.vehicles[start:start + params["size"]]}


class AsyncTransport(Transport):
    async def get(self, path, params):
        return Transport.get(self, path, params)


TOTALS = [0, 1, 49, 50, 51, 100, 120, 149]


@pytest.mark.parametrize("total", TOTALS)
def test_the_client_returns_every_vehicle(load, total):
    vehicles = load("fleetapi").FleetClient(Transport(total)).list_vehicles(page_size=50)
    assert [v["id"] for v in vehicles] == list(range(total))


@pytest.mark.parametrize("total", TOTALS)
def test_the_async_client_returns_every_vehicle(load, total):
    client = load("fleetapi.aio").AsyncFleetClient(AsyncTransport(total))
    vehicles = asyncio.run(client.list_vehicles(page_size=50))
    assert [v["id"] for v in vehicles] == list(range(total))
