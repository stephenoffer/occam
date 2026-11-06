"""One worker process handling one delivery against file-backed fakes.

usage: delivery_worker.py <world.json> <delivery.json> <result.json>

The world file holds what the outside world remembers across worker restarts: the
refunds PayGate has committed, the mail the relay accepted, and the faults still to
come. Backoff sleeps are skipped so a retry loop cannot slow the suite down.
"""

import json
import os
import sys
import time

time.sleep = lambda seconds: None

world_path, delivery_path, result_path = sys.argv[1:4]

from refundhook.consumer import handle_delivery  # noqa: E402
from refundhook.gateway import GatewayTimeout, GatewayUnavailable  # noqa: E402
from refundhook.mailer import MailError  # noqa: E402

KILLED = 137


def load():
    with open(world_path) as handle:
        return json.load(handle)


def save(world):
    temporary = world_path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(world, handle)
    os.replace(temporary, world_path)


class FileGateway:
    def __init__(self, down):
        self.down = down

    def create_refund(self, order_id, amount_cents, idempotency_key=None):
        world = load()
        world["gateway_calls"] += 1
        fault = world["gateway_faults"].pop(0) if world["gateway_faults"] else None
        save(world)
        if self.down:
            raise GatewayUnavailable("connection refused")
        if fault == "unavailable":
            raise GatewayUnavailable("connection refused")
        if fault == "timeout_before_apply":
            raise GatewayTimeout("timed out")
        if fault == "kill_before_apply":
            os._exit(KILLED)

        refund = next((r for r in world["refunds"]
                       if idempotency_key and r["idempotency_key"] == idempotency_key), None)
        if refund is None:
            refund = {"id": f"re_{len(world['refunds']) + 1:04d}", "order_id": order_id,
                      "amount_cents": amount_cents, "idempotency_key": idempotency_key}
            world["refunds"].append(refund)
            save(world)

        if fault == "timeout_after_apply":
            raise GatewayTimeout("timed out")
        if fault == "kill_after_apply":
            os._exit(KILLED)
        return refund["id"]

    def list_refunds(self, order_id):
        if self.down:
            raise GatewayUnavailable("connection refused")
        return [r for r in load()["refunds"] if r["order_id"] == order_id]


class FileMailer:
    def __init__(self, down):
        self.down = down

    def send(self, to, subject, body):
        world = load()
        fault = world["mail_faults"].pop(0) if world["mail_faults"] else None
        save(world)
        if self.down or fault == "fail":
            raise MailError("relay refused the message")
        if fault == "kill_before_send":
            os._exit(KILLED)
        world["mail"].append({"to": to, "subject": subject, "body": body})
        save(world)


with open(delivery_path) as handle:
    spec = json.load(handle)

gateway = FileGateway(spec["gateway_down"])
mailer = FileMailer(spec["mail_down"])
try:
    outcome = {"status": handle_delivery(spec["payload"], gateway, mailer, spec["db_path"])}
except Exception as exc:
    outcome = {"status": 500, "exception": f"{type(exc).__name__}: {exc}"}

with open(result_path, "w") as handle:
    json.dump(outcome, handle)
