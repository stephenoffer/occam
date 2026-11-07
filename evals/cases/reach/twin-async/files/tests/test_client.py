from fleetapi import FleetClient


class FakeTransport:
    def __init__(self, total):
        self.vehicles = [{"id": n} for n in range(total)]

    def get(self, path, params):
        start = (params["page"] - 1) * params["size"]
        return {"total": len(self.vehicles), "items": self.vehicles[start:start + params["size"]]}


def test_two_full_pages():
    assert len(FleetClient(FakeTransport(100)).list_vehicles()) == 100
