class FakeGateway:
    def __init__(self):
        self.refunds = []

    def create_refund(self, order_id, amount_cents, idempotency_key=None):
        for refund in self.refunds:
            if idempotency_key and refund["idempotency_key"] == idempotency_key:
                return refund["id"]
        refund = {"id": f"re_{len(self.refunds) + 1}", "order_id": order_id,
                  "amount_cents": amount_cents, "idempotency_key": idempotency_key}
        self.refunds.append(refund)
        return refund["id"]

    def list_refunds(self, order_id):
        return [refund for refund in self.refunds if refund["order_id"] == order_id]


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})
