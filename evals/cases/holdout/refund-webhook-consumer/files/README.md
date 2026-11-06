# refundhook

Receives refund webhooks from the payments provider. For each refund request it
creates a refund at PayGate and emails the customer a receipt quoting the refund id.

    refundhook/app.py        WSGI entry point, maps exceptions to a 500
    refundhook/consumer.py   handle_delivery: one webhook delivery
    refundhook/gateway.py    PayGate client (vendored)
    refundhook/mailer.py     SMTP client (vendored)

Run the tests with `pytest`.

## Provider webhook contract

The provider POSTs one JSON document per delivery:

    {
      "id": "dlv_7Hq2",
      "type": "refund.requested",
      "attempt": 1,
      "event": {
        "id": "evt_41c9",
        "order_id": "ord_1001",
        "amount_cents": 2500,
        "customer_email": "pat@example.invalid"
      }
    }

- `id` identifies the delivery attempt. Every attempt gets a new one.
- `event.id` identifies the refund request and stays the same on every redelivery.
- An order can have several refund requests, including several for the same amount.
- Other `type` values may be sent. We answer those with a 204 and do nothing.
- A 2xx response acknowledges the delivery and the provider will not send it again.
- Any other response, or no response within 10 seconds, and the provider delivers it
  again with backoff, for up to 72 hours.
