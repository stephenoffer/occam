# webhook-relay

Receives signed webhooks from our payment provider and forwards them to internal services.
Every inbound request must carry a valid `x-signature` HMAC of its body.

Run the tests with `npm test`.
