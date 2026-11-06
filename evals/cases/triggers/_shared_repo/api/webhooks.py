def parse_payment_event(payload):
    if "id" not in payload or "amount" not in payload:
        raise ValueError("bad payload")
    return payload["id"], int(payload["amount"])
