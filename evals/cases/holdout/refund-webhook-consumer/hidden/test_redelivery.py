"""Exactly one refund and one receipt per refund request, under the prompt's failures.

Every delivery runs in a fresh process, as a restarted worker would, and every
redelivery carries a new delivery id. A delivery that crashes, raises, hangs or
answers non-2xx is redelivered, as the provider's contract in the README says.
"""

import json
import subprocess
from pathlib import Path

import pytest

WORKER = str(Path(__file__).parent / "delivery_worker.py")
MAX_ATTEMPTS = 6
WORKER_TIMEOUT = 20


class World:
    def __init__(self, py, directory: Path):
        self.py = py
        self.directory = directory
        self.db_path = str(directory / "refunds.sqlite3")
        self.world_path = directory / "world.json"
        self.deliveries = 0
        self.world = {"refunds": [], "mail": [], "gateway_calls": 0, "gateway_faults": [], "mail_faults": []}
        self._save()

    def _save(self):
        self.world_path.write_text(json.dumps(self.world))

    def _load(self):
        self.world = json.loads(self.world_path.read_text())
        return self.world

    def fail_gateway(self, *faults):
        self._load()["gateway_faults"] = list(faults)
        self._save()

    def fail_mail(self, *faults):
        self._load()["mail_faults"] = list(faults)
        self._save()

    def deliver(self, event, *, gateway_down=False, mail_down=False, event_type="refund.requested"):
        """Run one delivery attempt in a new worker. Returns its status, or None if it died or hung."""
        self.deliveries += 1
        n = self.deliveries
        spec = {
            "payload": {"id": f"dlv_{n:04d}", "type": event_type, "attempt": n, "event": event},
            "db_path": self.db_path, "gateway_down": gateway_down, "mail_down": mail_down,
        }
        spec_path = self.directory / f"delivery-{n}.json"
        result_path = self.directory / f"result-{n}.json"
        spec_path.write_text(json.dumps(spec))
        try:
            self.py(WORKER, str(self.world_path), str(spec_path), str(result_path), timeout=WORKER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return None
        if not result_path.exists():
            return None
        return json.loads(result_path.read_text())["status"]

    def deliver_until_acknowledged(self, event):
        for _ in range(MAX_ATTEMPTS):
            status = self.deliver(event)
            if isinstance(status, int) and 200 <= status < 300:
                return status
        pytest.fail(f"never acknowledged after {MAX_ATTEMPTS} deliveries of {event['id']}")

    def refunds(self, order_id):
        return [r for r in self._load()["refunds"] if r["order_id"] == order_id]

    def receipts(self, email):
        return [m for m in self._load()["mail"] if m["to"] == email]


def acknowledged(status):
    return isinstance(status, int) and 200 <= status < 300


@pytest.fixture
def world(py, tmp_path):
    return World(py, tmp_path)


def refund_request(event_id, order_id=None, amount_cents=2500, email=None):
    return {
        "id": event_id,
        "order_id": order_id or f"ord_{event_id}",
        "amount_cents": amount_cents,
        "customer_email": email or f"{event_id}@example.invalid",
    }


def assert_one_refund_and_receipt(world, event):
    refunds = world.refunds(event["order_id"])
    receipts = world.receipts(event["customer_email"])
    assert len(refunds) == 1, f"expected one refund, PayGate has {refunds}"
    assert refunds[0]["amount_cents"] == event["amount_cents"]
    assert len(receipts) == 1, f"expected one receipt, the relay accepted {len(receipts)}"


def test_clean_delivery_refunds_and_sends_receipt(world):
    event = refund_request("evt_clean")
    assert acknowledged(world.deliver(event))
    assert_one_refund_and_receipt(world, event)


def test_other_event_types_are_ignored(world):
    event = refund_request("evt_other")
    status = world.deliver(event, event_type="refund.settled")
    assert status == 204
    assert world.refunds(event["order_id"]) == []
    assert world.receipts(event["customer_email"]) == []


def test_redelivery_after_success_changes_nothing(world):
    event = refund_request("evt_again")
    assert acknowledged(world.deliver(event))
    for _ in range(3):
        assert acknowledged(world.deliver(event)), "a repeat of a finished request should be acknowledged"
    assert_one_refund_and_receipt(world, event)


def test_timeout_after_gateway_applied_does_not_double_refund(world):
    event = refund_request("evt_lost_reply")
    world.fail_gateway("timeout_after_apply")
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_timeout_before_gateway_applied_still_refunds(world):
    event = refund_request("evt_lost_request")
    world.fail_gateway("timeout_before_apply")
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_repeated_timeouts_do_not_multiply_refunds(world):
    event = refund_request("evt_flaky")
    world.fail_gateway("timeout_after_apply", "timeout_before_apply", "timeout_after_apply", "unavailable")
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_gateway_outage_then_recovery(world):
    event = refund_request("evt_outage")
    status = world.deliver(event, gateway_down=True)
    assert not acknowledged(status), "acknowledging during an outage loses the refund"
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_worker_killed_after_gateway_applied(world):
    event = refund_request("evt_killed_after")
    world.fail_gateway("kill_after_apply")
    assert world.deliver(event) is None
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_worker_killed_before_gateway_call(world):
    event = refund_request("evt_killed_before")
    world.fail_gateway("kill_before_apply")
    assert world.deliver(event) is None
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_worker_killed_before_receipt_sent(world):
    event = refund_request("evt_killed_mail")
    world.fail_mail("kill_before_send")
    assert world.deliver(event) is None
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_mail_outage_then_recovery(world):
    event = refund_request("evt_mail_down")
    status = world.deliver(event, mail_down=True)
    assert not acknowledged(status), "acknowledging during a mail outage loses the receipt"
    world.deliver_until_acknowledged(event)
    assert_one_refund_and_receipt(world, event)


def test_distinct_requests_same_order_and_amount_each_refund(world):
    first = refund_request("evt_part_1", order_id="ord_shared", amount_cents=1000, email="shared@example.invalid")
    second = refund_request("evt_part_2", order_id="ord_shared", amount_cents=1000, email="shared@example.invalid")
    assert acknowledged(world.deliver(first))
    assert acknowledged(world.deliver(second))
    assert acknowledged(world.deliver(first))
    assert len(world.refunds("ord_shared")) == 2
    assert len(world.receipts("shared@example.invalid")) == 2


def test_interleaved_redelivery(world):
    first = refund_request("evt_first")
    second = refund_request("evt_second")
    world.fail_gateway("timeout_after_apply")
    world.deliver(first)
    assert acknowledged(world.deliver(second))
    world.deliver_until_acknowledged(first)
    assert_one_refund_and_receipt(world, first)
    assert_one_refund_and_receipt(world, second)


def test_receipt_quotes_the_refund_that_was_created(world):
    event = refund_request("evt_quote")
    world.fail_gateway("timeout_after_apply")
    world.deliver_until_acknowledged(event)
    refund = world.refunds(event["order_id"])[0]
    assert refund["id"] in world.receipts(event["customer_email"])[0]["body"]
