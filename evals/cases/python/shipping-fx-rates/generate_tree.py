#!/usr/bin/env python3
"""Generate tidewater's operational packages around the hand-written core. Deterministic, standard library only."""

import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from string import Template

# Each entity's fields, in order: key (str), label (str), count (int), day (date), measure (Decimal).
DOMAINS = {
    "berthing": {"BerthWindow": "window_id terminal length_metres opens_on tariff_factor",
                 "MooringPlan": "plan_id quay line_count agreed_on tension_limit",
                 "QuayBlock": "block_id operator bollards surveyed_on depth_metres"},
    "bunkering": {"FuelDelivery": "delivery_id supplier tonnes_lifted delivered_on sulphur_pct",
                  "TankSounding": "sounding_id tank ullage_cm sounded_on density",
                  "StemOrder": "stem_id grade volume_tonnes ordered_on premium"},
    "cargo": {"Consignment": "consignment_id shipper pieces packed_on gross_tonnes",
              "DangerousGoods": "dg_id un_class packages declared_on flash_point",
              "CargoNote": "note_id surveyor damaged_units noted_on loss_ratio"},
    "chartering": {"Fixture": "fixture_id charterer duration_days fixed_on daily_hire",
                   "LaytimeClock": "clock_id berth_name hours_used started_on demurrage_factor",
                   "HireStatement": "statement_id broker off_hire_hours issued_on commission_pct"},
    "compliance": {"PortStateInspection": "inspection_id authority findings inspected_on risk_score",
                   "Deficiency": "deficiency_id code_group days_open raised_on severity",
                   "ScreeningCheck": "check_id list_name matches screened_on confidence"},
    "containers": {"BoxUnit": "box_id owner_code cycles built_on tare_tonnes",
                   "ReeferPlug": "plug_id rack alarms plugged_on setpoint",
                   "SealRecord": "seal_id issuer rechecks applied_on tamper_score"},
    "crew": {"Seafarer": "seafarer_id rank months_served joined_on day_rate",
             "RotationPlan": "rotation_id pool relief_count starts_on overtime_factor",
             "CompetencyCert": "cert_id capacity endorsements issued_on score"},
    "drydock": {"YardSlot": "slot_id yard days_booked begins_on deposit_ratio",
                "WorkOrder": "order_id trade man_hours opened_on estimate",
                "HullPatch": "patch_id frame plate_count marked_on thickness_mm"},
    "fleet": {"Vessel": "vessel_id flag deadweight built_on draft_metres",
              "MainEngine": "engine_id maker cylinders overhauled_on rated_power",
              "ClassSurvey": "survey_id society items_open due_on condition_score"},
    "insurance": {"CoverNote": "cover_id underwriter clauses bound_on sum_insured",
                  "PremiumInstalment": "instalment_id payer sequence falls_due_on amount_due",
                  "HullValuation": "valuation_id assessor comparables valued_on market_value"},
    "maintenance": {"SparePart": "part_id location on_hand counted_on unit_cost",
                    "JobCard": "card_id system steps raised_on labour_hours",
                    "RunningHours": "meter_id machinery reading read_on load_factor"},
    "manifests": {"BillOfLading": "bill_id consignee parties issued_on freight_tonnes",
                  "ManifestLine": "line_id commodity units entered_on line_weight",
                  "Amendment": "amendment_id requester revision filed_on fee_factor"},
    "pilotage": {"PilotRoster": "roster_id station pilots_on_call effective_on fatigue_index",
                 "BoardingEvent": "boarding_id ladder delays boarded_on swell_height",
                 "TugBooking": "booking_id tug_name bollard_pull ordered_for hourly_factor"},
    "ports": {"PortCall": "call_id unlocode moves arrived_on turn_hours",
              "AnchorageSlot": "anchorage_id zone waiting_ships allotted_on holding_score",
              "AgentAppointment": "appointment_id agency disbursements appointed_on advance_ratio"},
    "safety": {"DrillRecord": "drill_id scenario participants held_on rating",
               "NearMiss": "report_id department actions occurred_on potential_severity",
               "LifeboatCheck": "lifeboat_id davit defects checked_on engine_hours"},
    "stowage": {"BayPlan": "plan_id service tiers planned_on stack_weight",
                "LashingSet": "set_id rod_type rods inspected_on wear_ratio",
                "BallastLog": "entry_id tank_group exchanges logged_on salinity"},
    "terminals": {"QuayCrane": "crane_id spreader moves_per_hour serviced_on outreach",
                  "GateMove": "move_id haulier wait_minutes gated_on gross_weight",
                  "YardStack": "stack_id block_code height stacked_on dwell_factor"},
    "tracking": {"PositionFix": "fix_id source satellites fixed_at speed_knots",
                 "GeofenceAlert": "alert_id fence crossings raised_at dwell_hours",
                 "VoyageLeg": "leg_id waypoint legs_left departed_on distance_nm"},
    "warehousing": {"RackBin": "bin_id aisle capacity audited_on fill_ratio",
                    "StockMove": "stock_move_id picker cases moved_on net_weight",
                    "CycleCount": "count_id zone_code variances counted_on accuracy"},
    "weather": {"RouteForecast": "forecast_id model_name horizon_hours issued_on wave_height",
                "StormAdvisory": "advisory_id basin category issued_at wind_knots",
                "SeaStateReport": "report_ref reporter douglas_scale observed_on swell_period"},
}
WORDS = ["Anchor", "Beacon", "Cutter", "Delta", "Ebbtide", "Fathom", "Galley", "Hawser", "Inlet", "Jetty", "Keel", "Lagoon",
         "Mizzen", "Narrows", "Offing", "Pier", "Quay", "Reef", "Shoal", "Tiller"]
STATE_SETS = [("draft", "submitted", "approved", "rejected"), ("logged", "triaged", "assigned", "closed"),
              ("planned", "confirmed", "underway", "completed", "cancelled"), ("open", "held", "released"),
              ("received", "checked", "disputed", "settled", "written_off")]
EVENTS = ["submit", "review", "confirm", "escalate", "complete", "hold", "release", "dispute"]


def snake(name):
    return "".join(("_" + c.lower()) if c.isupper() and i else c.lower() for i, c in enumerate(name))


class Entity:
    def __init__(self, pkg, cls, spec, rng):
        self.pkg, self.cls, self.rng = pkg, cls, rng
        self.snake = snake(cls)
        self.key, self.label, self.count, self.day, self.measure = spec.split()
        self.title = self.snake.replace("_", " ")
        self.sample = {
            self.key: f"{cls[:2].upper()}-{rng.randint(100, 999)}",
            self.label: rng.choice(WORDS),
            self.count: str(rng.randint(6, 90)),
            self.day: (date(2024, 1, 1) + timedelta(days=rng.randint(0, 800))).isoformat(),
            self.measure: str(Decimal(rng.randint(120, 9800)) / 100),
        }

    def fill(self, text, **extra):
        return Template(text).substitute(E=self.cls, S=self.snake, P=self.pkg, T=self.title, K=self.key, L=self.label,
                                         C=self.count, D=self.day, M=self.measure, CU=self.count.upper(),
                                         MU=self.measure.upper(), **extra)


def models(e):
    r = e.rng
    extra = r.choice([
        '''
    def per_$C(self) -> Decimal:
        return self.$M / self.$C if self.$C else Decimal(0)
''', '''
    def scaled(self, factor: Decimal) -> $E:
        return replace(self, $M=self.$M * factor)
''', '''
    def tag(self) -> str:
        return f"{self.$L}/{self.$K}"
''', '''
    def is_older_than(self, days: int, on: date) -> bool:
        return self.age_in_days(on) > days
'''])
    check = r.choice(['''if self.$M < 0:
            raise ValueError("$M can't be negative")''', '''if len(self.$K) > 40:
            raise ValueError("$K is too long")''', '''if not self.$L.strip():
            raise ValueError("$L can't be blank")'''])
    return e.fill(f'''"""$T records held by the $P desk."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class $E:
    $K: str
    $L: str
    $C: int
    $D: date
    $M: Decimal

    def __post_init__(self) -> None:
        if not self.$K:
            raise ValueError("a $T needs a $K")
        if self.$C < 0:
            raise ValueError("$C can't be negative")
        {check}

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> $E:
        return cls(
            $K=row["$K"].strip(),
            $L=row["$L"].strip(),
            $C=int(row["$C"]),
            $D=date.fromisoformat(row["$D"]),
            $M=Decimal(row["$M"]),
        )

    def to_row(self) -> dict[str, str]:
        return {{
            "$K": self.$K,
            "$L": self.$L,
            "$C": str(self.$C),
            "$D": self.$D.isoformat(),
            "$M": str(self.$M),
        }}

    def with_$M(self, value: Decimal) -> $E:
        return replace(self, $M=value)

    def age_in_days(self, on: date) -> int:
        return (on - self.$D).days
{extra}''')


def rules(e):
    r = e.rng
    label_rule = r.choice(['''    if not item.$L[:1].isupper():
        return "$L should start with a capital"
''', '''    if len(item.$L) > $width:
        return "$L is longer than $width characters"
''', '''    if any(ch.isdigit() for ch in item.$L):
        return "$L can't contain digits"
'''])
    age = r.choice(['''

def _not_from_the_future(item: $E) -> str | None:
    if item.$D > HORIZON:
        return "$D is past the planning horizon"
    return None
''', '''

def _not_ancient(item: $E) -> str | None:
    if item.$D < EARLIEST:
        return "$D predates the earliest record we accept"
    return None
'''])
    age_name = "_not_from_the_future" if "HORIZON" in age else "_not_ancient"
    return e.fill(f'''"""Acceptance rules for $T records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal

from tidewater.domain.$P.$S.models import $E

MAX_$CU = $max_count
MIN_$MU = Decimal("$floor")
HORIZON = date(2031, 12, 31)
EARLIEST = date(2015, 1, 1)
Rule = Callable[[$E], "str | None"]


def _within_limit(item: $E) -> str | None:
    if item.$C > MAX_$CU:
        return f"$C {{item.$C}} is over the limit of {{MAX_$CU}}"
    return None


def _above_floor(item: $E) -> str | None:
    if item.$M < MIN_$MU:
        return f"$M {{item.$M}} is under the floor of {{MIN_$MU}}"
    return None


def _label_shape(item: $E) -> str | None:
{label_rule}    return None
{age}

RULES: tuple[Rule, ...] = (_within_limit, _above_floor, _label_shape, {age_name})


def violations(item: $E) -> list[str]:
    found = (rule(item) for rule in RULES)
    return [message for message in found if message]


def is_acceptable(item: $E) -> bool:
    return not violations(item)


def rejected(items: Iterable[$E]) -> dict[str, list[str]]:
    return {{item.$K: problems for item in items if (problems := violations(item))}}
''', max_count=r.randint(120, 900), floor=r.choice(["0", "0.50", "1"]), width=r.randint(12, 24))


def store(e):
    r = e.rng
    extra = r.choice(['''
    def total_$C(self) -> int:
        return sum(item.$C for item in self._items.values())
''', '''
    def distinct_$L(self) -> list[str]:
        return sorted({item.$L for item in self._items.values()})
''', '''
    def largest(self, limit: int = 5) -> list[$E]:
        return self.sorted_by_$M(descending=True)[:limit]
'''])
    return e.fill(f'''"""In-memory working set of $T records for a desk session."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from tidewater.domain.$P.$S.models import $E


class ${{E}}Store:
    def __init__(self) -> None:
        self._items: dict[str, $E] = {{}}

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[$E]:
        return iter(self._items.values())

    def add(self, item: $E) -> None:
        if item.$K in self._items:
            raise ValueError(f"{{item.$K}} is already recorded")
        self._items[item.$K] = item

    def get(self, key: str) -> $E | None:
        return self._items.get(key)

    def remove(self, key: str) -> bool:
        return self._items.pop(key, None) is not None

    def find_by_$L(self, value: str) -> list[$E]:
        return [item for item in self._items.values() if item.$L == value]

    def sorted_by_$M(self, *, descending: bool = False) -> list[$E]:
        return sorted(self._items.values(), key=lambda item: item.$M, reverse=descending)

    def recorded_since(self, on: date) -> list[$E]:
        return [item for item in self._items.values() if item.$D >= on]
{extra}''')


def metrics(e):
    r = e.rng
    variant = r.randrange(3)
    if variant == 0:
        return e.fill('''"""Distribution of $C across $T records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from tidewater.domain.$P.$S.models import $E

BUCKET_WIDTH = $width


def bucket_of(value: int) -> int:
    return value // BUCKET_WIDTH * BUCKET_WIDTH


def histogram(items: Iterable[$E]) -> dict[int, int]:
    counts = Counter(bucket_of(item.$C) for item in items)
    return dict(sorted(counts.items()))


def fullest_bucket(items: Iterable[$E]) -> int | None:
    shape = histogram(items)
    return max(shape, key=lambda bucket: shape[bucket]) if shape else None
''', width=r.choice([5, 10, 25, 50]))
    if variant == 1:
        return e.fill('''"""Summary statistics of $M for $T records."""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from decimal import Decimal

from tidewater.domain.$P.$S.models import $E


def median_$M(items: Iterable[$E]) -> Decimal | None:
    values = [item.$M for item in items]
    return statistics.median(values) if values else None


def spread(items: Iterable[$E]) -> Decimal:
    values = [item.$M for item in items]
    return max(values) - min(values) if values else Decimal(0)


def share_above(items: Iterable[$E], threshold: Decimal) -> float:
    values = [item.$M for item in items]
    return sum(value > threshold for value in values) / len(values) if values else 0.0
''')
    return e.fill('''"""Totals grouped by $L for $T records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from tidewater.domain.$P.$S.models import $E


def totals_by_$L(items: Iterable[$E]) -> dict[str, Decimal]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in items:
        totals[item.$L] += item.$M
    return dict(totals)


def top_$L(items: Iterable[$E], limit: int = $limit) -> list[str]:
    totals = totals_by_$L(items)
    return sorted(totals, key=lambda name: (-totals[name], name))[:limit]


def weighted_mean(items: Iterable[$E]) -> Decimal:
    rows = list(items)
    weight = sum(item.$C for item in rows)
    return sum((item.$M * item.$C for item in rows), Decimal(0)) / weight if weight else Decimal(0)
''', limit=r.randint(3, 8))


def schedule(e):
    r = e.rng
    variant = r.randrange(3)
    if variant == 0:
        return e.fill('''"""Review intervals for $T records."""

from __future__ import annotations

from datetime import date, timedelta

from tidewater.domain.$P.$S.models import $E

REVIEW_EVERY_DAYS = $days


def next_review(item: $E) -> date:
    return item.$D + timedelta(days=REVIEW_EVERY_DAYS)


def is_due(item: $E, on: date) -> bool:
    return next_review(item) <= on


def days_overdue(item: $E, on: date) -> int:
    return max((on - next_review(item)).days, 0)
''', days=r.choice([14, 30, 45, 60, 90, 180]))
    if variant == 1:
        return e.fill('''"""Calendar month cycle for $T records."""

from __future__ import annotations

from datetime import date

from tidewater.core.dates import add_months, month_start
from tidewater.domain.$P.$S.models import $E

CYCLE_MONTHS = $months


def next_cycle(item: $E) -> date:
    return month_start(add_months(item.$D, CYCLE_MONTHS))


def is_due(item: $E, on: date) -> bool:
    return next_cycle(item) <= on


def cycles_elapsed(item: $E, on: date) -> int:
    months = (on.year - item.$D.year) * 12 + on.month - item.$D.month
    return max(months // CYCLE_MONTHS, 0)
''', months=r.choice([1, 2, 3, 6, 12]))
    return e.fill('''"""Weekly slot for following up $T records."""

from __future__ import annotations

from datetime import date, timedelta

from tidewater.domain.$P.$S.models import $E

FOLLOW_UP_WEEKDAY = $weekday


def next_follow_up(item: $E) -> date:
    ahead = (FOLLOW_UP_WEEKDAY - item.$D.weekday()) % 7 or 7
    return item.$D + timedelta(days=ahead)


def is_due(item: $E, on: date) -> bool:
    return next_follow_up(item) <= on


def weeks_outstanding(item: $E, on: date) -> int:
    return max((on - next_follow_up(item)).days // 7, 0)
''', weekday=r.randint(0, 4))


def codec(e):
    r = e.rng
    variant = r.randrange(3)
    if variant == 0:
        sep = r.choice(["|", ";", "~"])
        return e.fill('''"""Delimited interchange format for $T records."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tidewater.domain.$P.$S.models import $E

SEPARATOR = "$sep"


def encode(item: $E) -> str:
    parts = (item.$K, item.$L, str(item.$C), item.$D.isoformat(), str(item.$M))
    return SEPARATOR.join(parts)


def decode(line: str) -> $E:
    key, label, count, day, measure = line.strip().split(SEPARATOR)
    return $E(key, label, int(count), date.fromisoformat(day), Decimal(measure))
''', sep=sep)
    if variant == 1:
        return e.fill('''"""key=value interchange format for $T records."""

from __future__ import annotations

from tidewater.domain.$P.$S.models import $E


def encode(item: $E) -> str:
    return " ".join(f"{name}={value}" for name, value in item.to_row().items())


def decode(line: str) -> $E:
    pairs = dict(part.split("=", 1) for part in line.split())
    return $E.from_row(pairs)
''')
    return e.fill('''"""Fixed-width interchange format for $T records, as the terminal systems send it."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tidewater.core.text import pad
from tidewater.domain.$P.$S.models import $E

WIDTHS = ($wk, $wl, 8, 10, 14)


def encode(item: $E) -> str:
    cells = (item.$K, item.$L, str(item.$C), item.$D.isoformat(), str(item.$M))
    return "".join(pad(cell, width) for cell, width in zip(cells, WIDTHS))


def decode(line: str) -> $E:
    cells = []
    start = 0
    for width in WIDTHS:
        cells.append(line[start:start + width].strip())
        start += width
    return $E(cells[0], cells[1], int(cells[2]), date.fromisoformat(cells[3]), Decimal(cells[4]))
''', wk=r.randint(14, 20), wl=r.randint(14, 22))


def workflow(e):
    r = e.rng
    states = r.choice(STATE_SETS)
    moves = {}
    events = r.sample(EVENTS, k=len(EVENTS))
    for index, state in enumerate(states[:-1]):
        moves[(state, events[index % len(events)])] = states[index + 1]
    moves[(states[0], events[-1])] = states[-1]
    table = "\n".join(f'    ("{a}", "{b}"): "{c}",' for (a, b), c in moves.items())
    return e.fill(f'''"""Lifecycle of a $T."""

from __future__ import annotations

STATES = {states!r}
INITIAL = "{states[0]}"
TERMINAL = "{states[-1]}"
TRANSITIONS: dict[tuple[str, str], str] = {{
{table}
}}


def advance(state: str, event: str) -> str:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise ValueError(f"$T can't {{event}} from {{state}}") from None


def events_from(state: str) -> list[str]:
    return sorted(event for (origin, event) in TRANSITIONS if origin == state)


def is_terminal(state: str) -> bool:
    return not events_from(state)


def reachable_from(state: str) -> set[str]:
    seen = {{state}}
    frontier = [state]
    while frontier:
        current = frontier.pop()
        for (origin, _), target in TRANSITIONS.items():
            if origin == current and target not in seen:
                seen.add(target)
                frontier.append(target)
    return seen
''')


def report(e):
    r = e.rng
    fx_part = ""
    fx_import = ""
    if r.random() < 0.28:
        fx_import = "from tidewater.core import fx\n"
        fx_part = '''

def budget_value_in(item: $E, currency: str) -> Decimal:
    """Budget figures always use the annual contract rate."""
    if not fx.is_known_currency(currency):
        raise ValueError(f"unknown currency {currency}")
    return round_cents(item.$M * fx.contract_rate(fx.PIVOT, currency))
'''
    order = r.choice(["item.$D", "item.$K", "-item.$C"])
    columns = r.sample(["$K", "$L", "$C", "$D", "$M"], k=r.randint(3, 5))
    return e.fill(f'''"""Text board of $T records for the morning call."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

{fx_import}from tidewater.core.money import round_cents
from tidewater.core.tabular import render_rows
from tidewater.domain.$P.$S.models import $E

COLUMNS = {tuple(columns)!r}


def rows(items: Iterable[$E]) -> list[list[str]]:
    ordered = sorted(items, key=lambda item: {order})
    return [[str(getattr(item, column)) for column in COLUMNS] for item in ordered]


def board(items: Iterable[$E]) -> str:
    return render_rows(COLUMNS, rows(items))


def total_rounded(items: Iterable[$E]) -> Decimal:
    return round_cents(sum((item.$M for item in items), Decimal(0)))
{fx_part}''')


FAMILIES = {"models": models, "rules": rules, "store": store, "metrics": metrics, "schedule": schedule, "codec": codec,
            "workflow": workflow, "report": report}


def desk(pkg, entities):
    lines = [f'"""Desk operations for {pkg}."""', "", "from __future__ import annotations", "",
             "from collections.abc import Mapping", "from datetime import date", ""]
    for e in entities:
        lines += [f"from tidewater.domain.{pkg}.{e.snake} import report as {e.snake}_report",
                  f"from tidewater.domain.{pkg}.{e.snake} import rules as {e.snake}_rules",
                  f"from tidewater.domain.{pkg}.{e.snake} import schedule as {e.snake}_schedule",
                  f"from tidewater.domain.{pkg}.{e.snake}.models import {e.cls}",
                  f"from tidewater.domain.{pkg}.{e.snake}.store import {e.cls}Store"]
    for e in entities:
        lines += ["", "", f"def intake_{e.snake}(store: {e.cls}Store, row: Mapping[str, str]) -> list[str]:",
                  f'    """Validate a {e.title} row and keep it if it passes. Returns the problems found."""',
                  f"    item = {e.cls}.from_row(row)", f"    problems = {e.snake}_rules.violations(item)", "    if not problems:",
                  "        store.add(item)", "    return problems", "", "",
                  f"def due_{e.snake}(store: {e.cls}Store, on: date) -> list[str]:",
                  f"    return sorted(item.{e.key} for item in store if {e.snake}_schedule.is_due(item, on))", "", "",
                  f"def {e.snake}_board(store: {e.cls}Store) -> str:", f"    return {e.snake}_report.board(store)"]
    return "\n".join(lines) + "\n"


def digest(pkg, entities):
    lines = [f'"""Weekly digest for {pkg}."""', "", "from __future__ import annotations", "", "from datetime import date", ""]
    for e in entities:
        lines.append(f"from tidewater.domain.{pkg}.{e.snake}.store import {e.cls}Store")
    params = ", ".join(f"{e.snake}: {e.cls}Store" for e in entities)
    lines += ["", "", f"def digest({params}, since: date) -> dict[str, int]:", "    return {"]
    lines += [f'        "{e.snake}": len({e.snake}.recorded_since(since)),' for e in entities]
    lines += ["    }"]
    return "\n".join(lines) + "\n"


def domain_tests(pkg, entities):
    lines = ["from datetime import date", "from decimal import Decimal", "", "import pytest", ""]
    for e in entities:
        for family in ("codec", "metrics", "report", "rules", "schedule", "workflow"):
            lines.append(f"from tidewater.domain.{pkg}.{e.snake} import {family} as {e.snake}_{family}")
        lines += [f"from tidewater.domain.{pkg}.{e.snake}.models import {e.cls}",
                  f"from tidewater.domain.{pkg}.{e.snake}.store import {e.cls}Store"]
    lines.append("")
    for e in entities:
        lines += [f"{e.snake.upper()}_ROW = {e.sample!r}", ""]
    for e in entities:
        row, s, cls = f"{e.snake.upper()}_ROW", e.snake, e.cls
        lines += [f'''
def test_{s}_row_round_trip():
    assert {cls}.from_row({row}).to_row() == {row}


def test_{s}_rejects_a_negative_{e.count}():
    with pytest.raises(ValueError):
        {cls}.from_row({{**{row}, "{e.count}": "-1"}})


def test_{s}_codec_round_trip():
    item = {cls}.from_row({row})
    assert {s}_codec.decode({s}_codec.encode(item)) == item


def test_{s}_sample_passes_the_rules():
    assert {s}_rules.is_acceptable({cls}.from_row({row}))


def test_{s}_over_limit_is_reported():
    item = {cls}.from_row({{**{row}, "{e.count}": "100000"}})
    assert any("{e.count}" in problem for problem in {s}_rules.violations(item))


def test_{s}_store_rejects_duplicates():
    store = {cls}Store()
    store.add({cls}.from_row({row}))
    with pytest.raises(ValueError):
        store.add({cls}.from_row({row}))
    assert len(store) == 1


def test_{s}_workflow_reaches_its_end():
    assert {s}_workflow.TERMINAL in {s}_workflow.reachable_from({s}_workflow.INITIAL)
    assert {s}_workflow.is_terminal({s}_workflow.TERMINAL)


def test_{s}_is_due_eventually():
    assert {s}_schedule.is_due({cls}.from_row({row}), date(2040, 1, 1))


def test_{s}_board_lists_the_row():
    assert {s}_report.board([{cls}.from_row({row})]).count("\\n") >= 1


def test_{s}_total_rounds():
    item = {cls}.from_row({row})
    assert {s}_report.total_rounded([item, item]) == (item.{e.measure} * 2).quantize(Decimal("0.01"))
''']
    lines.insert(0, "# Metrics modules are exercised through the desks; imported here so a typo fails fast.")
    return "\n".join(lines).rstrip() + "\n"


def main(root):
    rng = random.Random(4343)
    def emit(path, text):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    for pkg, specs in DOMAINS.items():
        entities = [Entity(pkg, cls, spec, rng) for cls, spec in specs.items()]
        emit(f"tidewater/domain/{pkg}/__init__.py", f'"""{pkg.capitalize()} operations."""\n')
        for e in entities:
            emit(f"tidewater/domain/{pkg}/{e.snake}/__init__.py", f'"""{e.title.capitalize()} records."""\n')
            for family, generate in FAMILIES.items():
                emit(f"tidewater/domain/{pkg}/{e.snake}/{family}.py", generate(e))
        emit(f"tidewater/services/desks/{pkg}.py", desk(pkg, entities))
        emit(f"tidewater/services/digests/{pkg}.py", digest(pkg, entities))
        emit(f"tests/domain/test_{pkg}.py", domain_tests(pkg, entities))
        emit(f"docs/domains/{pkg}.md", f"# {pkg.capitalize()}\n\nRecords kept by this desk:\n\n"
             + "".join(f"- `{e.cls}`: {e.title}, identified by `{e.key}`, grouped by `{e.label}`.\n" for e in entities))
    emit("tidewater/services/desks/__init__.py", '"""One module of desk operations per domain package."""\n')
    emit("tidewater/services/digests/__init__.py", '''"""Weekly digests, one module per domain package, loaded by name."""

from importlib import import_module
from types import ModuleType


def digest_module(package: str) -> ModuleType:
    return import_module(f"tidewater.services.digests.{package}")
''')


if __name__ == "__main__":
    main(Path(sys.argv[1]))
