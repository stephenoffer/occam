"""Catalog, coupon and subscription endpoints."""

from __future__ import annotations

from .. import auth, store
from ..auth import admin_only, authenticated
from ..db import transaction
from ..http import BadRequest, NotFound, Request, Response, RouteTable, json_response
from ..models import Plan, Subscription
from ..services import pricing
from ..services import subscriptions as subscription_service
from ..utils import formatting, money

routes = RouteTable()


def _plan_json(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "name": plan.name,
        "interval": plan.interval,
        "price_cents": pricing.plan_period_price(plan),
    }


def _subscription_json(sub: Subscription) -> dict:
    return {
        "id": sub.id,
        "customer_id": sub.customer_id,
        "plan_id": sub.plan_id,
        "pending_plan_id": sub.pending_plan_id,
        "quantity": sub.quantity,
        "price_cents": sub.price_cents,
        "status": sub.status,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": bool(sub.cancel_at_period_end),
    }


def _require_subscription(request: Request) -> Subscription:
    sub = store.get_subscription(request.conn, request.tenant_id, request.param_int("subscription_id"))
    if sub is None:
        raise NotFound("subscription not found")
    return sub


@routes.get("/plans")
def list_plans(request: Request) -> Response:
    plans = store.list_plans(request.conn)
    headers = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"}
    return json_response({"plans": [_plan_json(p) for p in plans]}, headers=headers)


@routes.put("/admin/plans/{plan_id}")
@authenticated
def update_plan_price(request: Request) -> Response:
    plan_id = request.params["plan_id"]
    monthly_cents = request.json().get("monthly_cents")
    if not isinstance(monthly_cents, int) or monthly_cents <= 0:
        raise BadRequest("monthly_cents must be a positive integer")
    if store.get_plan(request.conn, plan_id) is None:
        raise NotFound("plan not found")
    with transaction(request.conn):
        store.update_plan_price(request.conn, plan_id, monthly_cents)
    return json_response(_plan_json(store.get_plan(request.conn, plan_id)))


@routes.post("/admin/tenants/{tenant_id}/api-keys")
@admin_only
def create_api_key(request: Request) -> Response:
    key = auth.generate_api_key()
    with transaction(request.conn):
        store.insert_api_key(request.conn, request.param_int("tenant_id"), auth.hash_api_key(key))
    return json_response({"api_key": key}, status=201)


@routes.post("/coupons")
@authenticated
def create_coupon(request: Request) -> Response:
    body = request.json()
    code = body.get("code")
    percent_off = body.get("percent_off")
    amount_off = body.get("amount_off")
    if not code or (percent_off is None) == (amount_off is None):
        raise BadRequest("code and exactly one of percent_off or amount_off are required")
    if percent_off is not None and not 0 < int(percent_off) <= 100:
        raise BadRequest("percent_off must be between 1 and 100")
    amount_off_cents = money.parse_amount(str(amount_off), "USD") if amount_off is not None else None
    with transaction(request.conn):
        coupon_id = store.insert_coupon(
            request.conn, request.tenant_id, code, percent_off=percent_off, amount_off_cents=amount_off_cents,
            max_redemptions=body.get("max_redemptions"), expires_on=body.get("expires_on"),
        )
    return json_response({"id": coupon_id, "code": code}, status=201)


@routes.post("/subscriptions")
@authenticated
def create_subscription(request: Request) -> Response:
    body = request.json()
    if "customer_id" not in body or "plan_id" not in body:
        raise BadRequest("customer_id and plan_id are required")
    customer = store.get_customer(request.conn, request.tenant_id, int(body["customer_id"]))
    if customer is None:
        raise NotFound("customer not found")
    plan = pricing.get_plan_cached(request.conn, body["plan_id"])
    if plan is None or not plan.active:
        raise BadRequest("unknown plan")
    sub = subscription_service.create_subscription(
        request.conn,
        request.app.gateway,
        tenant_id=request.tenant_id,
        customer=customer,
        plan=plan,
        quantity=int(body.get("quantity", 1)),
        trial=bool(body.get("trial", True)),
        trial_days=request.app.settings.trial_days,
        price_cents=body.get("price_cents"),
        coupon_code=body.get("coupon"),
    )
    return json_response(_subscription_json(sub), status=201)


@routes.get("/subscriptions/{subscription_id}")
@authenticated
def get_subscription(request: Request) -> Response:
    return json_response(_subscription_json(_require_subscription(request)))


@routes.get("/subscriptions/{subscription_id}/preview")
@authenticated
def preview_next_invoice(request: Request) -> Response:
    sub = _require_subscription(request)
    customer = store.get_customer(request.conn, request.tenant_id, sub.customer_id)
    if customer is None:
        raise NotFound("customer not found")
    estimate = formatting.estimated_total(sub.quantity * sub.price_cents, customer.country, customer.currency)
    return json_response(estimate)


@routes.post("/subscriptions/{subscription_id}/change-plan")
@authenticated
def change_plan(request: Request) -> Response:
    sub = _require_subscription(request)
    new_plan = pricing.get_plan_cached(request.conn, request.json().get("plan_id", ""))
    if new_plan is None or not new_plan.active:
        raise BadRequest("unknown plan")
    updated, invoice = subscription_service.change_plan(
        request.conn, request.app.gateway, tenant_id=request.tenant_id, subscription_id=sub.id, new_plan=new_plan
    )
    payload = _subscription_json(updated)
    payload["invoice_id"] = invoice.id if invoice else None
    return json_response(payload)


@routes.post("/subscriptions/{subscription_id}/cancel")
@authenticated
def cancel_subscription(request: Request) -> Response:
    sub = _require_subscription(request)
    immediate = bool(request.json().get("immediate", True))
    updated = subscription_service.cancel_subscription(
        request.conn, tenant_id=request.tenant_id, subscription_id=sub.id, immediate=immediate
    )
    return json_response(_subscription_json(updated))
