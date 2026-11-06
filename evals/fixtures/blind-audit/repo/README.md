# Subledger

Subscriptions and invoicing API for multi-tenant SaaS products. Each tenant (a
SaaS vendor) manages its own customers, subscriptions and invoices with an API
key. Card payments go through the PayBridge gateway.

## Running it

```
pip install -e '.[dev]'
gunicorn 'subledger.app:create_app()' --workers 4 --threads 2
python -m subledger.worker        # one or more worker processes
python -m pytest
```

Configuration comes from the environment, see `.env.example`. The service uses
SQLite and the standard library, including a small WSGI router in `subledger/http.py`.

## Billing rules

These rules are the contract with tenants.

### Money

- Amounts are stored as integers in the currency's minor unit.
- Supported currencies: USD, EUR, GBP and JPY. JPY has no minor unit, so 1000
  means 1,000 yen and renders as `1,000 JPY`.
- Rounding is half-up to the minor unit, everywhere. A preview shows exactly what
  the invoice will later charge.

### Plans

| Plan    | Monthly | Annual    |
|---------|---------|-----------|
| starter | $29     | $295.80   |
| growth  | $99     | $1,009.80 |
| scale   | $299    | $3,049.80 |

Annual plans are twelve months at 15% off. Prices come from the catalog: tenants
cannot set their own price through the API. Only platform admins can change a
catalog price, and a change applies to new subscriptions straight away. Existing
subscriptions keep the price they signed up at.

### Trials

Trials last 14 days. No invoice is issued until the trial ends.

### Periods and renewal

- `current_period_start` and `current_period_end` are inclusive UTC dates.
- The billing anchor is preserved. A subscription that starts on January 31
  renews on February 28, then March 31, then April 30.

### Plan changes

- **Upgrades** apply immediately and are charged pro rata:
  `(new_price - old_price) * remaining_days / period_days`. `remaining_days`
  includes the day of the change, and `period_days` includes both ends of the
  period.
- **Downgrades** take effect at the next renewal. No credit is issued, and the
  customer pays the lower price from that renewal onward.

### Cancellation

Cancelling is at period end by default: the customer keeps access and is not
billed again. Pass `{"immediate": true}` to end access now.

### Discounts and tax

- Coupons apply before tax. Tax is calculated on the discounted subtotal.
- An invoice total is never negative.
- A coupon with `max_redemptions` of N can be redeemed exactly N times.
- Tax rates: US 0%, CA 5%, GB 20%, DE 19%, FR 20%.

### Invoices

- Numbers look like `INV-2026-000123` and are unique and sequential per tenant.
- Payment terms are net 14.
- Only `open` invoices can be voided.
- Only `paid` or `partially_refunded` invoices can be refunded, and total refunds
  can never exceed the invoice total. Refunds go back to the card via PayBridge.
- `GET /invoices/{id}/pdf` returns the invoice as a PDF.
- Receipts list every line item with the tax breakdown.

### Failed payments

A failed charge is retried three times, at 3, 5 and 7 days after the due date. If
the last retry fails the invoice becomes `uncollectible` and the subscription is
cancelled.

### Customers

- An email address is unique per tenant. Two tenants can have the same customer.
- Deleting a customer is a soft delete. Invoices and customer records are retained
  for seven years for tax purposes.

### Reporting

- MRR counts `active` subscriptions only. Trialing and past-due subscriptions are
  excluded. Annual plans are normalised by dividing by twelve.
- Revenue reports take inclusive `from` and `to` dates.
- Churn is the share of subscriptions active at the start of a month that were
  cancelled during it.

## API conventions

- Authenticate with `Authorization: Bearer <api key>`.
- List endpoints take `page` (starting at 1) and `limit` (default 25, maximum 100).
- The rate limit is 120 requests per minute per API key.
- `GET /plans` and `GET /healthz` are public.
- All timestamps and dates are UTC.

## Webhooks

PayBridge posts events to `/webhooks/gateway`. Every event is signed with
HMAC-SHA256 in the `X-PayBridge-Signature` header, and unsigned requests are
rejected. Each event is processed exactly once, including across restarts and
across workers. Processing failures return a 5xx so that PayBridge redelivers.
