"""Front-desk engine for a tool hire shop.

Everything the counter staff do goes through here: the catalog of hire assets, customer
accounts, pricing, advance bookings, check-out and return, reminders, maintenance work
orders, invoicing, the stored shop state, the reports and the command line.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HireError(Exception):
    """Base class for anything the desk refuses to do. The command line prints these."""


class ValidationError(HireError):
    """Input that can never be right, such as a negative amount or a malformed date."""


class NotFoundError(HireError):
    """A reference to something the shop has no record of."""


class ConflictError(HireError):
    """The request is well formed, but collides with a booking or a hire."""


class StateError(HireError):
    """The record exists, but is in the wrong state for this operation."""


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value) -> Decimal:
    """Round anything number-like to whole cents, half up, the way the till does."""
    if isinstance(value, float):
        raise ValidationError(f"money must not be passed as a float: {value!r}")
    try:
        return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValidationError(f"not a money amount: {value!r}") from exc


def money_str(value) -> str:
    return f"{money(value):.2f}"


def percent_of(amount, percent) -> Decimal:
    return money(Decimal(str(amount)) * Decimal(str(percent)) / Decimal(100))


def sum_money(values: Iterable) -> Decimal:
    total = ZERO
    for value in values:
        total += money(value)
    return money(total)


def split_evenly(amount, parts: int) -> list[Decimal]:
    """Share an amount across parts so the shares add back up exactly. Early parts take the odd cents."""
    if parts <= 0:
        raise ValidationError("cannot split an amount into no parts")
    amount = money(amount)
    share = (amount / parts).quantize(CENTS, rounding="ROUND_DOWN")
    shares = [share] * parts
    remainder = amount - share * parts
    index = 0
    while remainder > 0:
        shares[index] += CENTS
        remainder -= CENTS
        index += 1
    return shares


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

ONE_DAY = dt.timedelta(days=1)


def parse_date(text) -> dt.date:
    if isinstance(text, dt.date):
        return text
    try:
        return dt.date.fromisoformat(str(text))
    except ValueError as exc:
        raise ValidationError(f"not a date (expected YYYY-MM-DD): {text!r}") from exc


def iso(day: dt.date | None) -> str | None:
    return day.isoformat() if day is not None else None


def date_span(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    """Every day from start up to but not including end."""
    day = start
    while day < end:
        yield day
        day += ONE_DAY


@dataclass
class ShopCalendar:
    """Which days the shop opens. Weekdays are numbered Monday=0, as in datetime."""

    holidays: set[dt.date] = field(default_factory=set)
    closed_weekdays: frozenset[int] = frozenset({6})

    def is_open(self, day: dt.date) -> bool:
        return day.weekday() not in self.closed_weekdays and day not in self.holidays

    def open_days_between(self, after: dt.date, upto: dt.date) -> int:
        """Count the open days after one date, up to and including another."""
        count = 0
        day = after + ONE_DAY
        while day <= upto:
            if self.is_open(day):
                count += 1
            day += ONE_DAY
        return count

    def next_open_day(self, day: dt.date) -> dt.date:
        day += ONE_DAY
        while not self.is_open(day):
            day += ONE_DAY
        return day

    def previous_open_day(self, day: dt.date) -> dt.date:
        day -= ONE_DAY
        while not self.is_open(day):
            day -= ONE_DAY
        return day

    def add_open_days(self, start: dt.date, count: int) -> dt.date:
        day = start
        for _ in range(count):
            day = self.next_open_day(day)
        return day

    def to_dict(self) -> dict:
        return {
            "holidays": sorted(iso(day) for day in self.holidays),
            "closed_weekdays": sorted(self.closed_weekdays),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShopCalendar":
        return cls(
            holidays={parse_date(day) for day in data.get("holidays", [])},
            closed_weekdays=frozenset(data.get("closed_weekdays", [6])),
        )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

CONDITIONS = ("new", "good", "fair", "worn", "unusable")
ASSET_STATUSES = ("available", "on_hire", "in_service", "retired")


@dataclass
class Category:
    code: str
    name: str
    daily_rate: Decimal
    weekly_rate: Decimal
    deposit: Decimal
    service_interval_days: int = 90
    late_grace_days: int = 1

    def __post_init__(self):
        self.daily_rate = money(self.daily_rate)
        self.weekly_rate = money(self.weekly_rate)
        self.deposit = money(self.deposit)
        if self.daily_rate <= 0 or self.weekly_rate <= 0:
            raise ValidationError(f"{self.code}: rates must be positive")
        if self.weekly_rate > self.daily_rate * 7:
            raise ValidationError(f"{self.code}: a week must not cost more than seven days")
        if self.late_grace_days < 0:
            raise ValidationError(f"{self.code}: late grace cannot be negative")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "daily_rate": money_str(self.daily_rate),
            "weekly_rate": money_str(self.weekly_rate),
            "deposit": money_str(self.deposit),
            "service_interval_days": self.service_interval_days,
            "late_grace_days": self.late_grace_days,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Category":
        return cls(**data)


@dataclass
class Asset:
    tag: str
    category: str
    description: str
    replacement_value: Decimal
    condition: str = "good"
    status: str = "available"
    acquired_on: dt.date | None = None
    last_serviced_on: dt.date | None = None
    hours_used: int = 0

    def __post_init__(self):
        self.replacement_value = money(self.replacement_value)
        self.acquired_on = parse_date(self.acquired_on) if self.acquired_on else None
        self.last_serviced_on = parse_date(self.last_serviced_on) if self.last_serviced_on else None
        if self.condition not in CONDITIONS:
            raise ValidationError(f"{self.tag}: unknown condition {self.condition!r}")
        if self.status not in ASSET_STATUSES:
            raise ValidationError(f"{self.tag}: unknown status {self.status!r}")

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "category": self.category,
            "description": self.description,
            "replacement_value": money_str(self.replacement_value),
            "condition": self.condition,
            "status": self.status,
            "acquired_on": iso(self.acquired_on),
            "last_serviced_on": iso(self.last_serviced_on),
            "hours_used": self.hours_used,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Asset":
        return cls(**data)


def downgrade_condition(condition: str, steps: int = 1) -> str:
    """Move a condition down the scale, stopping at the bottom."""
    index = min(CONDITIONS.index(condition) + steps, len(CONDITIONS) - 1)
    return CONDITIONS[index]


class Catalog:
    """Hire categories and the physical assets in them."""

    def __init__(self):
        self.categories: dict[str, Category] = {}
        self.assets: dict[str, Asset] = {}

    def add_category(self, category: Category) -> Category:
        if category.code in self.categories:
            raise ConflictError(f"category {category.code} already exists")
        self.categories[category.code] = category
        return category

    def category(self, code: str) -> Category:
        try:
            return self.categories[code]
        except KeyError:
            raise NotFoundError(f"no category {code}") from None

    def add_asset(self, asset: Asset) -> Asset:
        if asset.tag in self.assets:
            raise ConflictError(f"asset {asset.tag} already exists")
        self.category(asset.category)
        self.assets[asset.tag] = asset
        return asset

    def asset(self, tag: str) -> Asset:
        try:
            return self.assets[tag]
        except KeyError:
            raise NotFoundError(f"no asset {tag}") from None

    def category_of(self, tag: str) -> Category:
        return self.category(self.asset(tag).category)

    def assets_in(self, code: str, include_retired: bool = False) -> list[Asset]:
        found = [asset for asset in self.assets.values() if asset.category == code]
        if not include_retired:
            found = [asset for asset in found if asset.status != "retired"]
        return sorted(found, key=lambda asset: asset.tag)

    def retire(self, tag: str) -> Asset:
        asset = self.asset(tag)
        if asset.status == "on_hire":
            raise StateError(f"{tag} is out on hire, so it cannot be retired")
        asset.status = "retired"
        return asset

    def search(self, text: str) -> list[Asset]:
        needle = text.casefold()
        matches = [
            asset
            for asset in self.assets.values()
            if needle in asset.description.casefold() or needle in asset.tag.casefold()
        ]
        return sorted(matches, key=lambda asset: asset.tag)

    def replacement_value_of(self, code: str) -> Decimal:
        return sum_money(asset.replacement_value for asset in self.assets_in(code))


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Tier:
    """What a kind of customer gets. Deposit is a percentage of the category's deposit."""

    code: str
    hire_discount_percent: int
    deposit_percent: int
    extra_grace_days: int
    credit_terms_days: int


TIERS = {
    "walk_in": Tier("walk_in", 0, 100, 0, 0),
    "trade": Tier("trade", 10, 50, 1, 14),
    "contractor": Tier("contractor", 15, 0, 2, 30),
}


@dataclass
class Customer:
    id: str
    name: str
    email: str
    tier: str = "walk_in"
    credit_limit: Decimal = ZERO
    blocked_reason: str | None = None

    def __post_init__(self):
        self.credit_limit = money(self.credit_limit)
        if self.tier not in TIERS:
            raise ValidationError(f"{self.id}: unknown tier {self.tier!r}")
        if not EMAIL_RE.match(self.email):
            raise ValidationError(f"{self.id}: malformed email {self.email!r}")

    @property
    def terms(self) -> Tier:
        return TIERS[self.tier]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "tier": self.tier,
            "credit_limit": money_str(self.credit_limit),
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Customer":
        return cls(**data)


class CustomerBook:
    def __init__(self):
        self.customers: dict[str, Customer] = {}

    def add(self, customer: Customer) -> Customer:
        if customer.id in self.customers:
            raise ConflictError(f"customer {customer.id} already exists")
        self.customers[customer.id] = customer
        return customer

    def get(self, customer_id: str) -> Customer:
        try:
            return self.customers[customer_id]
        except KeyError:
            raise NotFoundError(f"no customer {customer_id}") from None

    def block(self, customer_id: str, reason: str) -> Customer:
        if not reason.strip():
            raise ValidationError("blocking a customer needs a reason")
        customer = self.get(customer_id)
        customer.blocked_reason = reason
        return customer

    def unblock(self, customer_id: str) -> Customer:
        customer = self.get(customer_id)
        customer.blocked_reason = None
        return customer

    def by_tier(self, tier: str) -> list[Customer]:
        return sorted((c for c in self.customers.values() if c.tier == tier), key=lambda c: c.id)

    def search(self, text: str) -> list[Customer]:
        needle = text.casefold()
        return sorted(
            (c for c in self.customers.values() if needle in c.name.casefold() or needle in c.email.casefold()),
            key=lambda c: c.id,
        )


def check_can_hire(customer: Customer, outstanding: Decimal, new_charge: Decimal) -> None:
    """Refuse a hire for a blocked customer, or one that would pass their credit limit."""
    if customer.blocked_reason:
        raise StateError(f"{customer.id} is blocked: {customer.blocked_reason}")
    if customer.terms.credit_terms_days and outstanding + new_charge > customer.credit_limit:
        raise StateError(
            f"{customer.id}: {money_str(outstanding + new_charge)} would pass the credit limit "
            f"of {money_str(customer.credit_limit)}"
        )


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

OPEN_DAYS_PER_HIRE_WEEK = 6
WAIVER_PERCENT = 8
DELIVERY_ZONES = {
    "collect": Decimal("0.00"),
    "local": Decimal("15.00"),
    "county": Decimal("35.00"),
    "regional": Decimal("60.00"),
}


def hire_days(calendar: ShopCalendar, start: dt.date, end: dt.date) -> int:
    """Open days a hire is charged for. Going out and coming back the same day counts as one."""
    if end < start:
        raise ValidationError("a hire cannot end before it starts")
    return max(1, calendar.open_days_between(start, end))


def hire_charge(category: Category, days: int, tier: Tier) -> Decimal:
    """Whole weeks at the weekly rate, then odd days, never paying more for the odd days than another week."""
    if days <= 0:
        raise ValidationError("a hire must last at least one day")
    weeks, odd_days = divmod(days, OPEN_DAYS_PER_HIRE_WEEK)
    odd_cost = min(category.daily_rate * odd_days, category.weekly_rate)
    gross = category.weekly_rate * weeks + odd_cost
    return money(gross - percent_of(gross, tier.hire_discount_percent))


def required_deposit(category: Category, tier: Tier) -> Decimal:
    return percent_of(category.deposit, tier.deposit_percent)


def delivery_fee(zone: str) -> Decimal:
    try:
        return DELIVERY_ZONES[zone]
    except KeyError:
        raise ValidationError(f"unknown delivery zone {zone!r}") from None


def waiver_fee(hire: Decimal) -> Decimal:
    """The optional damage waiver, charged on the hire itself and not on delivery."""
    return percent_of(hire, WAIVER_PERCENT)


@dataclass
class Quote:
    category: str
    start: dt.date
    end: dt.date
    days: int
    hire: Decimal
    delivery: Decimal
    waiver: Decimal
    deposit: Decimal

    @property
    def total_due_today(self) -> Decimal:
        return money(self.hire + self.delivery + self.waiver + self.deposit)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "start": iso(self.start),
            "end": iso(self.end),
            "days": self.days,
            "hire": money_str(self.hire),
            "delivery": money_str(self.delivery),
            "waiver": money_str(self.waiver),
            "deposit": money_str(self.deposit),
            "total_due_today": money_str(self.total_due_today),
        }


def build_quote(
    state: "ShopState",
    category_code: str,
    start: dt.date,
    end: dt.date,
    customer_id: str | None = None,
    zone: str = "collect",
    with_waiver: bool = False,
) -> Quote:
    category = state.catalog.category(category_code)
    tier = state.customers.get(customer_id).terms if customer_id else TIERS["walk_in"]
    days = hire_days(state.calendar, start, end)
    hire = hire_charge(category, days, tier)
    return Quote(
        category=category_code,
        start=start,
        end=end,
        days=days,
        hire=hire,
        delivery=delivery_fee(zone),
        waiver=waiver_fee(hire) if with_waiver else ZERO,
        deposit=required_deposit(category, tier),
    )


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

BOOKING_STATUSES = ("held", "fulfilled", "cancelled")


@dataclass
class Booking:
    id: str
    customer: str
    category: str
    start: dt.date
    end: dt.date
    status: str = "held"
    note: str = ""

    def __post_init__(self):
        self.start = parse_date(self.start)
        self.end = parse_date(self.end)
        if self.end <= self.start:
            raise ValidationError(f"{self.id}: a booking must end after it starts")
        if self.status not in BOOKING_STATUSES:
            raise ValidationError(f"{self.id}: unknown status {self.status!r}")

    def overlaps(self, start: dt.date, end: dt.date) -> bool:
        return self.start < end and start < self.end

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer": self.customer,
            "category": self.category,
            "start": iso(self.start),
            "end": iso(self.end),
            "status": self.status,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Booking":
        return cls(**data)


def held_bookings(state: "ShopState", category: str, start: dt.date, end: dt.date) -> list[Booking]:
    return sorted(
        (
            booking
            for booking in state.bookings.values()
            if booking.status == "held" and booking.category == category and booking.overlaps(start, end)
        ),
        key=lambda booking: (booking.start, booking.id),
    )


def rentals_blocking(state: "ShopState", category: str, start: dt.date, end: dt.date) -> list["Rental"]:
    """Open hires in a category that have not come back by the end of the period."""
    blocking = []
    for rental in state.rentals.values():
        if rental.status not in ("open", "disputed"):
            continue
        if state.catalog.asset(rental.asset).category != category:
            continue
        if rental.started_on < end and start < max(effective_due(rental) + ONE_DAY, start + ONE_DAY):
            blocking.append(rental)
    return blocking


def free_count(state: "ShopState", category: str, start: dt.date, end: dt.date) -> int:
    """How many more of a category could go out for the whole of a period."""
    usable = [a for a in state.catalog.assets_in(category) if a.status in ("available", "on_hire")]
    taken = len(rentals_blocking(state, category, start, end)) + len(held_bookings(state, category, start, end))
    return max(0, len(usable) - taken)


def availability_by_day(state: "ShopState", category: str, start: dt.date, end: dt.date) -> list[dict]:
    return [
        {"day": iso(day), "free": free_count(state, category, day, day + ONE_DAY)}
        for day in date_span(start, end)
    ]


def reserve(state: "ShopState", customer_id: str, category: str, start: dt.date, end: dt.date, note: str = "") -> Booking:
    customer = state.customers.get(customer_id)
    if customer.blocked_reason:
        raise StateError(f"{customer_id} is blocked: {customer.blocked_reason}")
    state.catalog.category(category)
    if free_count(state, category, start, end) < 1:
        raise ConflictError(f"no {category} free from {iso(start)} to {iso(end)}")
    booking = Booking(state.next_id("B"), customer_id, category, start, end, note=note)
    state.bookings[booking.id] = booking
    return booking


def cancel_booking(state: "ShopState", booking_id: str) -> Booking:
    booking = state.booking(booking_id)
    if booking.status != "held":
        raise StateError(f"{booking_id} is already {booking.status}")
    booking.status = "cancelled"
    return booking


# ---------------------------------------------------------------------------
# Rentals
# ---------------------------------------------------------------------------

LATE_RATE_MULTIPLIER = Decimal("1.5")
RENTAL_STATUSES = ("open", "returned", "disputed")
DAMAGE_GRADES = {
    "none": (0, 0),
    "scuffed": (5, 0),
    "repairable": (25, 1),
    "major": (60, 2),
    "total": (100, 4),
}


@dataclass
class Extension:
    new_due_on: dt.date
    approved_by: str

    def __post_init__(self):
        self.new_due_on = parse_date(self.new_due_on)

    def to_dict(self) -> dict:
        return {"new_due_on": iso(self.new_due_on), "approved_by": self.approved_by}


@dataclass
class Rental:
    id: str
    customer: str
    asset: str
    started_on: dt.date
    due_on: dt.date
    status: str = "open"
    returned_on: dt.date | None = None
    hire_charge: Decimal = ZERO
    deposit_paid: Decimal = ZERO
    deposit_refunded: Decimal = ZERO
    deposit_applied: Decimal = ZERO
    late_charge: Decimal = ZERO
    damage_charge: Decimal = ZERO
    extensions: list[Extension] = field(default_factory=list)
    dispute_reason: str | None = None

    def __post_init__(self):
        self.started_on = parse_date(self.started_on)
        self.due_on = parse_date(self.due_on)
        self.returned_on = parse_date(self.returned_on) if self.returned_on else None
        for name in ("hire_charge", "deposit_paid", "deposit_refunded", "deposit_applied", "late_charge", "damage_charge"):
            setattr(self, name, money(getattr(self, name)))
        self.extensions = [e if isinstance(e, Extension) else Extension(**e) for e in self.extensions]
        if self.status not in RENTAL_STATUSES:
            raise ValidationError(f"{self.id}: unknown status {self.status!r}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer": self.customer,
            "asset": self.asset,
            "started_on": iso(self.started_on),
            "due_on": iso(self.due_on),
            "status": self.status,
            "returned_on": iso(self.returned_on),
            "hire_charge": money_str(self.hire_charge),
            "deposit_paid": money_str(self.deposit_paid),
            "deposit_refunded": money_str(self.deposit_refunded),
            "deposit_applied": money_str(self.deposit_applied),
            "late_charge": money_str(self.late_charge),
            "damage_charge": money_str(self.damage_charge),
            "extensions": [extension.to_dict() for extension in self.extensions],
            "dispute_reason": self.dispute_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Rental":
        return cls(**data)


def effective_due(rental: Rental) -> dt.date:
    """The date a hire is really due back: the latest approved extension, or the original date."""
    if rental.extensions:
        return rental.extensions[-1].new_due_on
    return rental.due_on


def billable_late_days(state: "ShopState", rental: Rental, on: dt.date) -> int:
    """Days the late fee is charged for if the asset comes back on a given day.

    Only days the shop was open count, starting after the effective due date. The category's
    grace days and the customer tier's extra grace come off the front.
    """
    due = effective_due(rental)
    if on <= due:
        return 0
    category = state.catalog.category_of(rental.asset)
    tier = state.customers.get(rental.customer).terms
    grace = category.late_grace_days + tier.extra_grace_days
    return max(0, state.calendar.open_days_between(due, on) - grace)


def late_fee(state: "ShopState", rental: Rental, on: dt.date) -> Decimal:
    """The late fee for a return on a given day. Never more than it would cost to replace the asset."""
    days = billable_late_days(state, rental, on)
    if days == 0:
        return ZERO
    category = state.catalog.category_of(rental.asset)
    daily = money(category.daily_rate * LATE_RATE_MULTIPLIER)
    return min(daily * days, state.catalog.asset(rental.asset).replacement_value)


def held_deposit(rental: Rental) -> Decimal:
    """What the shop is still holding of the deposit paid for a hire."""
    return money(rental.deposit_paid - rental.deposit_refunded - rental.deposit_applied)


def damage_charge(state: "ShopState", rental: Rental, grade: str) -> Decimal:
    try:
        percent, _ = DAMAGE_GRADES[grade]
    except KeyError:
        raise ValidationError(f"unknown damage grade {grade!r}") from None
    return percent_of(state.catalog.asset(rental.asset).replacement_value, percent)


@dataclass
class Settlement:
    """What a return comes to. Charges are met from the deposit first."""

    rental: str
    returned_on: dt.date
    late_days: int
    late_fee: Decimal
    damage: Decimal
    deposit_applied: Decimal
    refund: Decimal
    balance_due: Decimal

    def to_dict(self) -> dict:
        return {
            "rental": self.rental,
            "returned_on": iso(self.returned_on),
            "late_days": self.late_days,
            "late_fee": money_str(self.late_fee),
            "damage": money_str(self.damage),
            "deposit_applied": money_str(self.deposit_applied),
            "refund": money_str(self.refund),
            "balance_due": money_str(self.balance_due),
        }


def settle_return(state: "ShopState", rental: Rental, on: dt.date, grade: str = "none") -> Settlement:
    if on < rental.started_on:
        raise ValidationError(f"{rental.id}: cannot come back before it went out")
    fee = late_fee(state, rental, on)
    damage = damage_charge(state, rental, grade)
    charges = money(fee + damage)
    held = held_deposit(rental)
    applied = min(charges, held)
    return Settlement(
        rental=rental.id,
        returned_on=on,
        late_days=billable_late_days(state, rental, on),
        late_fee=fee,
        damage=damage,
        deposit_applied=applied,
        refund=money(held - applied),
        balance_due=money(charges - applied),
    )


def open_rental(state: "ShopState", rental_id: str) -> Rental:
    rental = state.rental(rental_id)
    if rental.status == "returned":
        raise StateError(f"{rental_id} has already come back")
    if rental.status == "disputed":
        raise StateError(f"{rental_id} is in dispute: {rental.dispute_reason}")
    return rental


def checkout(state: "ShopState", customer_id: str, tag: str, start: dt.date, due: dt.date, booking_id: str | None = None) -> Rental:
    """Send an asset out on hire, charging the hire and taking the deposit."""
    customer = state.customers.get(customer_id)
    asset = state.catalog.asset(tag)
    if asset.status != "available":
        raise StateError(f"{tag} is {asset.status}")
    if asset.condition == "unusable":
        raise StateError(f"{tag} is unusable and must be serviced first")
    if booking_id:
        booking = state.booking(booking_id)
        if booking.status != "held" or booking.category != asset.category or booking.customer != customer_id:
            raise ConflictError(f"{booking_id} does not cover this hire")
        booking.status = "fulfilled"
    category = state.catalog.category(asset.category)
    charge = hire_charge(category, hire_days(state.calendar, start, due), customer.terms)
    check_can_hire(customer, state.outstanding(customer_id), charge)
    rental = Rental(
        id=state.next_id("R"),
        customer=customer_id,
        asset=tag,
        started_on=start,
        due_on=due,
        hire_charge=charge,
        deposit_paid=required_deposit(category, customer.terms),
    )
    state.rentals[rental.id] = rental
    asset.status = "on_hire"
    return rental


def extend_rental(state: "ShopState", rental_id: str, new_due: dt.date, approved_by: str) -> Rental:
    """Push the due date out, charging for the extra open days."""
    rental = open_rental(state, rental_id)
    current = effective_due(rental)
    if new_due <= current:
        raise ValidationError(f"{rental_id}: an extension must move the due date later than {iso(current)}")
    if not approved_by.strip():
        raise ValidationError("an extension needs a named approver")
    category = state.catalog.category_of(rental.asset)
    tier = state.customers.get(rental.customer).terms
    total_days = hire_days(state.calendar, rental.started_on, new_due)
    rental.hire_charge = hire_charge(category, total_days, tier)
    rental.extensions.append(Extension(new_due, approved_by))
    return rental


def checkin(state: "ShopState", rental_id: str, on: dt.date, grade: str = "none") -> Settlement:
    """Take an asset back: record the charges, the deposit movement and the asset's new condition."""
    rental = open_rental(state, rental_id)
    settlement = settle_return(state, rental, on, grade)
    asset = state.catalog.asset(rental.asset)
    _, steps = DAMAGE_GRADES[grade]
    asset.condition = downgrade_condition(asset.condition, steps)
    asset.status = "available"
    asset.hours_used += hire_days(state.calendar, rental.started_on, on) * 4
    rental.status = "returned"
    rental.returned_on = on
    rental.late_charge = settlement.late_fee
    rental.damage_charge = settlement.damage
    rental.deposit_applied = money(rental.deposit_applied + settlement.deposit_applied)
    rental.deposit_refunded = money(rental.deposit_refunded + settlement.refund)
    return settlement


def mark_disputed(state: "ShopState", rental_id: str, reason: str) -> Rental:
    """Put a hire on hold while the shop and customer sort something out. Nobody chases it meanwhile."""
    rental = open_rental(state, rental_id)
    if not reason.strip():
        raise ValidationError("a dispute needs a reason")
    rental.status = "disputed"
    rental.dispute_reason = reason
    return rental


def resolve_dispute(state: "ShopState", rental_id: str) -> Rental:
    rental = state.rental(rental_id)
    if rental.status != "disputed":
        raise StateError(f"{rental_id} is not in dispute")
    rental.status = "open"
    rental.dispute_reason = None
    return rental


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

REMINDER_STAGES = ((21, "final"), (7, "firm"), (1, "courtesy"))


def days_overdue(rental: Rental, on: dt.date) -> int:
    """Calendar days past the original due date.

    This drives the reminder letters only. Their cadence deliberately ignores extensions and
    opening hours, so that a customer who keeps extending still hears from us.
    """
    return max(0, (on - rental.due_on).days)


def rough_late_estimate(state: "ShopState", rental: Rental, on: dt.date) -> Decimal:
    """A ballpark figure for reminder letters, which say "around". Not what a return charges."""
    return money(state.catalog.category_of(rental.asset).daily_rate * days_overdue(rental, on))


def reminder_stage(days: int) -> str | None:
    for threshold, stage in REMINDER_STAGES:
        if days >= threshold:
            return stage
    return None


def reminder_letter(state: "ShopState", rental: Rental, on: dt.date) -> str | None:
    stage = reminder_stage(days_overdue(rental, on))
    if stage is None or rental.status != "open":
        return None
    customer = state.customers.get(rental.customer)
    asset = state.catalog.asset(rental.asset)
    opening = {
        "courtesy": "Just a reminder that",
        "firm": "Please return it promptly:",
        "final": "This is our final notice:",
    }[stage]
    return (
        f"To: {customer.email}\n"
        f"Subject: {stage} reminder for {rental.id}\n\n"
        f"Dear {customer.name},\n\n"
        f"{opening} {asset.description} ({asset.tag}) was due back on {iso(rental.due_on)}.\n"
        f"Charges so far are around {money_str(rough_late_estimate(state, rental, on))}.\n"
    )


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

WORK_ORDER_STATUSES = ("open", "closed")


@dataclass
class WorkOrder:
    id: str
    asset: str
    opened_on: dt.date
    reason: str
    status: str = "open"
    closed_on: dt.date | None = None
    cost: Decimal = ZERO
    notes: str = ""

    def __post_init__(self):
        self.opened_on = parse_date(self.opened_on)
        self.closed_on = parse_date(self.closed_on) if self.closed_on else None
        self.cost = money(self.cost)
        if self.status not in WORK_ORDER_STATUSES:
            raise ValidationError(f"{self.id}: unknown status {self.status!r}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset": self.asset,
            "opened_on": iso(self.opened_on),
            "reason": self.reason,
            "status": self.status,
            "closed_on": iso(self.closed_on),
            "cost": money_str(self.cost),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkOrder":
        return cls(**data)


def service_due_on(state: "ShopState", asset: Asset) -> dt.date | None:
    """When an asset next needs servicing, counted from its last service or from when we bought it."""
    last = asset.last_serviced_on or asset.acquired_on
    if last is None:
        return None
    interval = state.catalog.category(asset.category).service_interval_days
    return last + dt.timedelta(days=interval)


def assets_due_service(state: "ShopState", on: dt.date) -> list[Asset]:
    due = []
    for asset in state.catalog.assets.values():
        if asset.status in ("retired", "in_service"):
            continue
        when = service_due_on(state, asset)
        if asset.condition == "unusable" or (when is not None and when <= on):
            due.append(asset)
    return sorted(due, key=lambda asset: asset.tag)


def open_work_order(state: "ShopState", tag: str, on: dt.date, reason: str) -> WorkOrder:
    asset = state.catalog.asset(tag)
    if asset.status == "on_hire":
        raise StateError(f"{tag} is out on hire")
    if asset.status == "retired":
        raise StateError(f"{tag} has been retired")
    if asset.status == "in_service":
        raise ConflictError(f"{tag} is already being serviced")
    order = WorkOrder(state.next_id("W"), tag, on, reason)
    state.work_orders[order.id] = order
    asset.status = "in_service"
    return order


def close_work_order(state: "ShopState", order_id: str, on: dt.date, cost, notes: str = "", condition: str = "good") -> WorkOrder:
    order = state.work_order(order_id)
    if order.status != "open":
        raise StateError(f"{order_id} is already closed")
    if on < order.opened_on:
        raise ValidationError(f"{order_id}: cannot close before it was opened")
    if condition not in CONDITIONS:
        raise ValidationError(f"unknown condition {condition!r}")
    order.status = "closed"
    order.closed_on = on
    order.cost = money(cost)
    order.notes = notes
    asset = state.catalog.asset(order.asset)
    asset.status = "available"
    asset.condition = condition
    asset.last_serviced_on = on
    return order


def service_cost_of(state: "ShopState", tag: str) -> Decimal:
    return sum_money(order.cost for order in state.work_orders.values() if order.asset == tag and order.status == "closed")


# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------


@dataclass
class InvoiceLine:
    description: str
    amount: Decimal

    def __post_init__(self):
        self.amount = money(self.amount)

    def to_dict(self) -> dict:
        return {"description": self.description, "amount": money_str(self.amount)}


@dataclass
class Invoice:
    number: str
    customer: str
    rental: str | None
    issued_on: dt.date
    tax_rate: Decimal
    lines: list[InvoiceLine] = field(default_factory=list)
    credit_of: str | None = None
    paid: bool = False

    def __post_init__(self):
        self.issued_on = parse_date(self.issued_on)
        self.tax_rate = Decimal(str(self.tax_rate))
        self.lines = [line if isinstance(line, InvoiceLine) else InvoiceLine(**line) for line in self.lines]

    @property
    def subtotal(self) -> Decimal:
        return sum_money(line.amount for line in self.lines)

    @property
    def tax(self) -> Decimal:
        return money(self.subtotal * self.tax_rate)

    @property
    def total(self) -> Decimal:
        return money(self.subtotal + self.tax)

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "customer": self.customer,
            "rental": self.rental,
            "issued_on": iso(self.issued_on),
            "tax_rate": str(self.tax_rate),
            "lines": [line.to_dict() for line in self.lines],
            "credit_of": self.credit_of,
            "paid": self.paid,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Invoice":
        return cls(**data)


def invoice_for_rental(state: "ShopState", rental_id: str, on: dt.date) -> Invoice:
    """Bill a returned hire. The deposit is not income, so it stays off the invoice."""
    rental = state.rental(rental_id)
    if rental.status != "returned":
        raise StateError(f"{rental_id} has not come back yet")
    if any(i.rental == rental_id and i.credit_of is None for i in state.invoices.values()):
        raise ConflictError(f"{rental_id} has already been invoiced")
    asset = state.catalog.asset(rental.asset)
    lines = [InvoiceLine(f"Hire of {asset.description} ({asset.tag})", rental.hire_charge)]
    if rental.late_charge:
        lines.append(InvoiceLine("Late return", rental.late_charge))
    if rental.damage_charge:
        lines.append(InvoiceLine("Damage", rental.damage_charge))
    invoice = Invoice(state.next_id("INV"), rental.customer, rental_id, on, state.tax_rate, lines)
    state.invoices[invoice.number] = invoice
    return invoice


def credit_note(state: "ShopState", number: str, on: dt.date, reason: str) -> Invoice:
    """Cancel an invoice by issuing the same lines negated."""
    original = state.invoice(number)
    if original.credit_of is not None:
        raise StateError(f"{number} is itself a credit note")
    if any(i.credit_of == number for i in state.invoices.values()):
        raise ConflictError(f"{number} has already been credited")
    lines = [InvoiceLine(f"{reason}: {line.description}", -line.amount) for line in original.lines]
    credit = Invoice(state.next_id("INV"), original.customer, original.rental, on, original.tax_rate, lines, credit_of=number)
    state.invoices[credit.number] = credit
    return credit


def render_invoice(state: "ShopState", invoice: Invoice) -> str:
    customer = state.customers.get(invoice.customer)
    title = "CREDIT NOTE" if invoice.credit_of else "INVOICE"
    out = [f"{title} {invoice.number}", f"Issued {iso(invoice.issued_on)} to {customer.name}", ""]
    for line in invoice.lines:
        out.append(f"{line.description:<48}{money_str(line.amount):>10}")
    out.append(f"{'Subtotal':<48}{money_str(invoice.subtotal):>10}")
    out.append(f"{'Tax':<48}{money_str(invoice.tax):>10}")
    out.append(f"{'Total':<48}{money_str(invoice.total):>10}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Stored state
# ---------------------------------------------------------------------------

STATE_VERSION = 3


class ShopState:
    """All of a shop's records, as loaded from its state file."""

    def __init__(self, tax_rate="0.20"):
        self.tax_rate = Decimal(str(tax_rate))
        self.calendar = ShopCalendar()
        self.catalog = Catalog()
        self.customers = CustomerBook()
        self.bookings: dict[str, Booking] = {}
        self.rentals: dict[str, Rental] = {}
        self.work_orders: dict[str, WorkOrder] = {}
        self.invoices: dict[str, Invoice] = {}
        self.counters: dict[str, int] = {}

    def next_id(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}-{self.counters[prefix]}"

    def booking(self, booking_id: str) -> Booking:
        try:
            return self.bookings[booking_id]
        except KeyError:
            raise NotFoundError(f"no booking {booking_id}") from None

    def rental(self, rental_id: str) -> Rental:
        try:
            return self.rentals[rental_id]
        except KeyError:
            raise NotFoundError(f"no rental {rental_id}") from None

    def work_order(self, order_id: str) -> WorkOrder:
        try:
            return self.work_orders[order_id]
        except KeyError:
            raise NotFoundError(f"no work order {order_id}") from None

    def invoice(self, number: str) -> Invoice:
        try:
            return self.invoices[number]
        except KeyError:
            raise NotFoundError(f"no invoice {number}") from None

    def outstanding(self, customer_id: str) -> Decimal:
        """Unpaid invoices and open hire charges, which is what counts against a credit limit."""
        unpaid = sum_money(i.total for i in self.invoices.values() if i.customer == customer_id and not i.paid)
        open_hires = sum_money(
            r.hire_charge for r in self.rentals.values() if r.customer == customer_id and r.status != "returned"
        )
        return money(unpaid + open_hires)

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "tax_rate": str(self.tax_rate),
            "calendar": self.calendar.to_dict(),
            "categories": [c.to_dict() for c in self.catalog.categories.values()],
            "assets": [a.to_dict() for a in self.catalog.assets.values()],
            "customers": [c.to_dict() for c in self.customers.customers.values()],
            "bookings": [b.to_dict() for b in self.bookings.values()],
            "rentals": [r.to_dict() for r in self.rentals.values()],
            "work_orders": [w.to_dict() for w in self.work_orders.values()],
            "invoices": [i.to_dict() for i in self.invoices.values()],
            "counters": dict(self.counters),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShopState":
        version = data.get("version", 1)
        if version > STATE_VERSION:
            raise ValidationError(f"state file is version {version}, newer than this desk ({STATE_VERSION})")
        state = cls(data.get("tax_rate", "0.20"))
        state.calendar = ShopCalendar.from_dict(data.get("calendar", {}))
        for item in data.get("categories", []):
            state.catalog.add_category(Category.from_dict(item))
        for item in data.get("assets", []):
            state.catalog.add_asset(Asset.from_dict(item))
        for item in data.get("customers", []):
            state.customers.add(Customer.from_dict(item))
        for item in data.get("bookings", []):
            booking = Booking.from_dict(item)
            state.bookings[booking.id] = booking
        for item in data.get("rentals", []):
            rental = Rental.from_dict(_upgrade_rental(item, version))
            state.rentals[rental.id] = rental
        for item in data.get("work_orders", []):
            order = WorkOrder.from_dict(item)
            state.work_orders[order.id] = order
        for item in data.get("invoices", []):
            invoice = Invoice.from_dict(item)
            state.invoices[invoice.number] = invoice
        state.counters = dict(data.get("counters", {}))
        return state


def _upgrade_rental(item: dict, version: int) -> dict:
    """Older state files kept one combined deposit figure, and called the customer "hirer"."""
    item = dict(item)
    if version < 2 and "hirer" in item:
        item["customer"] = item.pop("hirer")
    if version < 3 and "deposit" in item:
        item["deposit_paid"] = item.pop("deposit")
    return item


def load_state(path) -> ShopState:
    try:
        text = Path(path).read_text()
    except OSError as exc:
        raise NotFoundError(f"cannot read state file {path}: {exc.strerror}") from exc
    try:
        return ShopState.from_dict(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc


def save_state(state: ShopState, path) -> None:
    """Replace the state file in one step, so an interrupted save cannot leave half a file."""
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(state.to_dict(), indent=2) + "\n")
    temporary.replace(target)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

OUTPUT_FORMATS = ("table", "csv", "json")


def render_rows(rows: list[dict], columns: tuple[str, ...], fmt: str = "table") -> str:
    """Print report rows the same way for every report. Values are expected to be display-ready."""
    if fmt == "json":
        return json.dumps(rows, indent=2)
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().rstrip("\n")
    if fmt != "table":
        raise ValidationError(f"unknown format {fmt!r}")
    if not rows:
        return "(nothing to report)"
    widths = {c: max(len(c), *(len(str(row[c])) for row in rows)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    rule = "  ".join("-" * widths[c] for c in columns)
    body = ["  ".join(str(row[c]).ljust(widths[c]) for c in columns) for row in rows]
    return "\n".join([header, rule, *body])


def utilization_rows(state: ShopState, as_of: dt.date, window_days: int = 30) -> list[dict]:
    """Per category, the share of asset-days in the window that were out on hire."""
    start = as_of - dt.timedelta(days=window_days)
    rows = []
    for code in sorted(state.catalog.categories):
        assets = state.catalog.assets_in(code)
        tags = {asset.tag for asset in assets}
        days_out = 0
        for rental in state.rentals.values():
            if rental.asset not in tags:
                continue
            came_back = rental.returned_on or as_of
            first = max(rental.started_on, start)
            last = min(came_back, as_of)
            days_out += max(0, (last - first).days)
        capacity = len(assets) * window_days
        percent = (Decimal(days_out) * 100 / capacity).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if capacity else Decimal("0.0")
        rows.append({"category": code, "assets": len(assets), "days_out": days_out, "utilization_percent": str(percent)})
    return rows


def deposit_rows(state: ShopState) -> list[dict]:
    """Every deposit the shop is still holding against a hire that has not come back."""
    rows = [
        {
            "rental": rental.id,
            "customer": rental.customer,
            "asset": rental.asset,
            "deposit_held": money_str(held_deposit(rental)),
        }
        for rental in state.rentals.values()
        if rental.status != "returned" and held_deposit(rental) > 0
    ]
    return sorted(rows, key=lambda row: row["rental"])


def revenue_rows(state: ShopState, start: dt.date, end: dt.date) -> list[dict]:
    """Invoiced income by category over a period, credit notes included."""
    totals: dict[str, Decimal] = {}
    for invoice in state.invoices.values():
        if not (start <= invoice.issued_on < end) or invoice.rental is None:
            continue
        code = state.catalog.asset(state.rental(invoice.rental).asset).category
        totals[code] = totals.get(code, ZERO) + invoice.subtotal
    return [{"category": code, "revenue": money_str(totals[code])} for code in sorted(totals)]


def service_rows(state: ShopState, on: dt.date) -> list[dict]:
    return [
        {
            "asset": asset.tag,
            "category": asset.category,
            "condition": asset.condition,
            "due_on": iso(service_due_on(state, asset)) or "",
        }
        for asset in assets_due_service(state, on)
    ]


def reminder_rows(state: ShopState, on: dt.date) -> list[dict]:
    rows = []
    for rental in state.rentals.values():
        stage = reminder_stage(days_overdue(rental, on))
        if rental.status == "open" and stage:
            rows.append({"rental": rental.id, "customer": rental.customer, "stage": stage, "days": days_overdue(rental, on)})
    return sorted(rows, key=lambda row: row["rental"])


def customer_rows(state: ShopState) -> list[dict]:
    """Each customer's standing, for the credit review."""
    return [
        {
            "customer": customer.id,
            "tier": customer.tier,
            "outstanding": money_str(state.outstanding(customer.id)),
            "credit_limit": money_str(customer.credit_limit),
            "blocked": "yes" if customer.blocked_reason else "no",
        }
        for customer in sorted(state.customers.customers.values(), key=lambda c: c.id)
    ]


def fleet_rows(state: ShopState) -> list[dict]:
    """What each category's fleet is worth, and what it has cost to keep it running."""
    rows = []
    for code in sorted(state.catalog.categories):
        assets = state.catalog.assets_in(code)
        rows.append({
            "category": code,
            "assets": len(assets),
            "replacement_value": money_str(state.catalog.replacement_value_of(code)),
            "service_cost": money_str(sum_money(service_cost_of(state, asset.tag) for asset in assets)),
        })
    return rows


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=OUTPUT_FORMATS, default="table")


def _add_as_of(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--as-of", help="report date, YYYY-MM-DD (default today)")


def _report_day(args: argparse.Namespace) -> dt.date:
    return parse_date(args.as_of) if args.as_of else dt.date.today()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolhire", description="Front desk for a tool hire shop.")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text)
        child.add_argument("state", help="path to the shop's state file")
        return child

    quote = command("quote", "price a hire without booking it")
    quote.add_argument("--category", required=True)
    quote.add_argument("--start", required=True)
    quote.add_argument("--end", required=True)
    quote.add_argument("--customer")
    quote.add_argument("--zone", default="collect", choices=sorted(DELIVERY_ZONES))
    quote.add_argument("--waiver", action="store_true")

    availability = command("availability", "show how many of a category are free each day")
    availability.add_argument("--category", required=True)
    availability.add_argument("--start", required=True)
    availability.add_argument("--end", required=True)
    _add_format(availability)

    book = command("book", "hold a category for a customer")
    book.add_argument("customer")
    book.add_argument("--category", required=True)
    book.add_argument("--start", required=True)
    book.add_argument("--end", required=True)
    book.add_argument("--note", default="")

    cancel = command("cancel-booking", "release a held booking")
    cancel.add_argument("booking")

    out = command("checkout", "send an asset out on hire")
    out.add_argument("customer")
    out.add_argument("asset")
    out.add_argument("--start", required=True)
    out.add_argument("--due", required=True)
    out.add_argument("--booking")

    extend = command("extend", "push a hire's due date out")
    extend.add_argument("rental")
    extend.add_argument("--to", required=True)
    extend.add_argument("--by", required=True, help="who approved it")

    back = command("return", "take an asset back")
    back.add_argument("rental")
    back.add_argument("--on", required=True)
    back.add_argument("--damage", default="none", choices=sorted(DAMAGE_GRADES))
    back.add_argument("--dry-run", action="store_true", help="show the charges, change nothing")

    dispute = command("dispute", "put a hire on hold")
    dispute.add_argument("rental")
    dispute.add_argument("--reason", required=True)

    settle = command("resolve-dispute", "take a hire off hold")
    settle.add_argument("rental")

    remind = command("reminders", "list hires that are due a reminder letter")
    _add_as_of(remind)
    remind.add_argument("--letters", action="store_true", help="print the letters themselves")
    _add_format(remind)

    utilization = command("utilization", "share of each category's time spent out on hire")
    _add_as_of(utilization)
    utilization.add_argument("--window", type=int, default=30, help="days to look back over")
    _add_format(utilization)

    deposits = command("deposits", "deposits held against hires that are still out")
    _add_format(deposits)

    revenue = command("revenue", "invoiced income by category")
    revenue.add_argument("--from", dest="start", required=True)
    revenue.add_argument("--to", dest="end", required=True)
    _add_format(revenue)

    service = command("service-due", "assets that need servicing")
    _add_as_of(service)
    _add_format(service)

    customers = command("customers", "each customer's outstanding balance and standing")
    _add_format(customers)

    fleet = command("fleet", "replacement value and service cost of each category")
    _add_format(fleet)

    work = command("work-order", "open a maintenance work order")
    work.add_argument("asset")
    work.add_argument("--on", required=True)
    work.add_argument("--reason", required=True)

    finish = command("close-work-order", "close a maintenance work order")
    finish.add_argument("order")
    finish.add_argument("--on", required=True)
    finish.add_argument("--cost", required=True)
    finish.add_argument("--notes", default="")
    finish.add_argument("--condition", default="good", choices=CONDITIONS)

    invoice = command("invoice", "bill a returned hire")
    invoice.add_argument("rental")
    invoice.add_argument("--on", required=True)

    credit = command("credit", "cancel an invoice with a credit note")
    credit.add_argument("number")
    credit.add_argument("--on", required=True)
    credit.add_argument("--reason", required=True)

    return parser


def _cmd_quote(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    quote = build_quote(
        state, args.category, parse_date(args.start), parse_date(args.end), args.customer, args.zone, args.waiver
    )
    print(json.dumps(quote.to_dict(), indent=2))
    return 0


def _cmd_availability(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    rows = availability_by_day(state, args.category, parse_date(args.start), parse_date(args.end))
    print(render_rows(rows, ("day", "free"), args.format))
    return 0


def _cmd_book(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    booking = reserve(state, args.customer, args.category, parse_date(args.start), parse_date(args.end), args.note)
    save_state(state, args.state)
    print(booking.id)
    return 0


def _cmd_cancel_booking(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    cancel_booking(state, args.booking)
    save_state(state, args.state)
    return 0


def _cmd_checkout(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    rental = checkout(state, args.customer, args.asset, parse_date(args.start), parse_date(args.due), args.booking)
    save_state(state, args.state)
    print(rental.id)
    return 0


def _cmd_extend(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    rental = extend_rental(state, args.rental, parse_date(args.to), args.by)
    save_state(state, args.state)
    print(f"{rental.id} now due {iso(effective_due(rental))}, hire charge {money_str(rental.hire_charge)}")
    return 0


def _cmd_return(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    on = parse_date(args.on)
    if args.dry_run:
        settlement = settle_return(state, open_rental(state, args.rental), on, args.damage)
    else:
        settlement = checkin(state, args.rental, on, args.damage)
        save_state(state, args.state)
    print(json.dumps(settlement.to_dict(), indent=2))
    return 0


def _cmd_dispute(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    mark_disputed(state, args.rental, args.reason)
    save_state(state, args.state)
    return 0


def _cmd_resolve_dispute(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    resolve_dispute(state, args.rental)
    save_state(state, args.state)
    return 0


def _cmd_reminders(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    on = _report_day(args)
    if args.letters:
        letters = (reminder_letter(state, rental, on) for rental in state.rentals.values())
        print("\n---\n".join(letter for letter in letters if letter))
        return 0
    print(render_rows(reminder_rows(state, on), ("rental", "customer", "stage", "days"), args.format))
    return 0


def _cmd_utilization(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    rows = utilization_rows(state, _report_day(args), args.window)
    print(render_rows(rows, ("category", "assets", "days_out", "utilization_percent"), args.format))
    return 0


def _cmd_deposits(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    print(render_rows(deposit_rows(state), ("rental", "customer", "asset", "deposit_held"), args.format))
    return 0


def _cmd_revenue(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    rows = revenue_rows(state, parse_date(args.start), parse_date(args.end))
    print(render_rows(rows, ("category", "revenue"), args.format))
    return 0


def _cmd_service_due(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    print(render_rows(service_rows(state, _report_day(args)), ("asset", "category", "condition", "due_on"), args.format))
    return 0


def _cmd_customers(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    columns = ("customer", "tier", "outstanding", "credit_limit", "blocked")
    print(render_rows(customer_rows(state), columns, args.format))
    return 0


def _cmd_fleet(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    print(render_rows(fleet_rows(state), ("category", "assets", "replacement_value", "service_cost"), args.format))
    return 0


def _cmd_work_order(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    order = open_work_order(state, args.asset, parse_date(args.on), args.reason)
    save_state(state, args.state)
    print(order.id)
    return 0


def _cmd_close_work_order(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    close_work_order(state, args.order, parse_date(args.on), args.cost, args.notes, args.condition)
    save_state(state, args.state)
    return 0


def _cmd_invoice(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    invoice = invoice_for_rental(state, args.rental, parse_date(args.on))
    save_state(state, args.state)
    print(render_invoice(state, invoice))
    return 0


def _cmd_credit(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    credit = credit_note(state, args.number, parse_date(args.on), args.reason)
    save_state(state, args.state)
    print(render_invoice(state, credit))
    return 0


HANDLERS = {
    "quote": _cmd_quote,
    "availability": _cmd_availability,
    "book": _cmd_book,
    "cancel-booking": _cmd_cancel_booking,
    "checkout": _cmd_checkout,
    "extend": _cmd_extend,
    "return": _cmd_return,
    "dispute": _cmd_dispute,
    "resolve-dispute": _cmd_resolve_dispute,
    "reminders": _cmd_reminders,
    "utilization": _cmd_utilization,
    "deposits": _cmd_deposits,
    "revenue": _cmd_revenue,
    "service-due": _cmd_service_due,
    "customers": _cmd_customers,
    "fleet": _cmd_fleet,
    "work-order": _cmd_work_order,
    "close-work-order": _cmd_close_work_order,
    "invoice": _cmd_invoice,
    "credit": _cmd_credit,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return HANDLERS[args.command](args)
    except HireError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
