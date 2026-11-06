"""Behavior goes through the command line and the signature the prompt fixes, so any way of threading the date is fine.

import-linter and mypy aren't available, so the contract and the strictness settings are enforced here from a copy of
the original configuration, with an AST walk standing in for each tool's rule.
"""

import ast
import configparser
import fnmatch
import io
import json
import re
import subprocess
import tokenize
import tomllib
import xml.etree.ElementTree as ET
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

BASELINE = Path(__file__).parent / "baseline"
MIN_VISIBLE_TESTS = 694  # the starter has 702; a few rate-specific tests may fairly be merged or rewritten

PER_USD = {
    date(2026, 1, 1): {"EUR": "0.92", "GBP": "0.79", "JPY": "150.00", "SGD": "1.34"},
    date(2026, 4, 1): {"EUR": "0.95", "GBP": "0.81", "JPY": "146.00", "SGD": "1.31"},
    date(2026, 7, 1): {"EUR": "0.88", "GBP": "0.76", "JPY": "158.00", "SGD": "1.36"},
    date(2026, 10, 1): {"EUR": "0.90", "GBP": "0.84", "JPY": "152.00", "SGD": "1.29"},
}
CONTRACT = {"EUR": "0.90", "GBP": "0.80", "JPY": "148.00", "SGD": "1.33"}
LANE_USD_PER_TONNE = {"SIN-RTM": "182.50", "RTM-NYC": "96.75", "YOK-SIN": "74.30"}
BACK_DATES = ["2026-02-14", "2026-05-02", "2026-08-20"]


def cents(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def crossed(base_per_usd, quote_per_usd):
    return (Decimal(quote_per_usd) / Decimal(base_per_usd)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def spot(base, quote, on):
    table = PER_USD[max(start for start in PER_USD if start <= date.fromisoformat(on))]
    return crossed("1" if base == "USD" else table[base], "1" if quote == "USD" else table[quote])


def contract(base, quote):
    return crossed("1" if base == "USD" else CONTRACT[base], "1" if quote == "USD" else CONTRACT[quote])


def adjustments(lane, currency, subtotal, on):
    total = cents(Decimal("45.00") * contract("USD", currency)) + cents(Decimal("25.00") * contract("USD", currency))
    if lane.startswith("SIN-"):
        total += cents(subtotal * Decimal("2.5") / 100)
    if lane == "YOK-SIN":
        total += cents(Decimal("30000") * contract("JPY", currency))
    if lane in {"RTM-NYC", "HAM-NYC"}:
        total += cents(Decimal("120.00") * spot("EUR", currency, on))
    return total


def expected_quote(lane, tonnes, currency, on):
    base = Decimal(LANE_USD_PER_TONNE[lane]) * Decimal(tonnes)
    rate = spot("USD", currency, on)
    subtotal = cents(base * rate) + cents(base * Decimal("0.085") * rate)
    return subtotal + adjustments(lane, currency, subtotal, on)


@pytest.fixture
def cli(py, tmp_path):
    counter = iter(range(1000))

    def run(command, document):
        path = tmp_path / f"document-{next(counter)}.json"
        path.write_text(json.dumps(document))
        done = py("-m", "tidewater", command, str(path))
        assert done.returncode == 0, f"{command} failed:\n{done.stdout[-500:]}\n{done.stderr[-1500:]}"
        return json.loads(done.stdout)

    return run


def test_spot_rate_uses_the_rate_in_force(py):
    done = py("-c", """
from datetime import date
from tidewater.core.fx import spot_rate
print(spot_rate("USD", "EUR", as_of=date(2026, 3, 31)))
print(spot_rate("USD", "EUR", as_of=date(2026, 4, 1)))
print(spot_rate("EUR", "GBP", as_of=date(2026, 7, 15)))
print(spot_rate("USD", "JPY", as_of=date(2031, 1, 1)))
""")
    assert done.returncode == 0, done.stderr[-1500:]
    assert done.stdout.split() == [str(spot("USD", "EUR", "2026-03-31")), str(spot("USD", "EUR", "2026-04-01")),
                                   str(spot("EUR", "GBP", "2026-07-15")), str(spot("USD", "JPY", "2031-01-01"))]


def test_spot_rate_needs_its_date(py):
    done = py("-c", """
import inspect, typing
from datetime import date
from tidewater.core.fx import spot_rate
parameter = inspect.signature(spot_rate).parameters["as_of"]
assert parameter.default is inspect.Parameter.empty, "as_of has a default"
assert typing.get_type_hints(spot_rate)["as_of"] is date, "as_of should be annotated as a date"
try:
    spot_rate("USD", "EUR")
except TypeError:
    pass
else:
    raise AssertionError("a call without as_of should not work")
""")
    assert done.returncode == 0, done.stderr[-1500:]


def test_no_rate_published_yet(py):
    done = py("-c", """
from datetime import date
from tidewater.core.errors import RateUnavailable
from tidewater.core.fx import spot_rate
try:
    spot_rate("USD", "EUR", as_of=date(2025, 12, 31))
except RateUnavailable:
    print("refused")
""")
    assert done.returncode == 0, done.stderr[-1500:]
    assert done.stdout.strip() == "refused"


@pytest.mark.parametrize("booked_on", BACK_DATES)
@pytest.mark.parametrize("lane", ["SIN-RTM", "YOK-SIN"])
def test_quote_is_priced_at_its_booking_date(cli, lane, booked_on):
    result = cli("quote", {"lane": lane, "tonnes": "40", "currency": "GBP", "booked_on": booked_on})
    assert Decimal(result["total"]) == expected_quote(lane, "40", "GBP", booked_on)


@pytest.mark.parametrize("booked_on", BACK_DATES)
def test_emission_levy_on_a_quote(cli, booked_on):
    result = cli("quote", {"lane": "RTM-NYC", "tonnes": "40", "currency": "GBP", "booked_on": booked_on})
    assert Decimal(result["total"]) == expected_quote("RTM-NYC", "40", "GBP", booked_on)


@pytest.mark.parametrize("issued_on", BACK_DATES)
def test_emission_levy_on_an_invoice(cli, issued_on):
    result = cli("invoice", {"invoice_id": "I-9", "lane": "RTM-NYC", "currency": "GBP", "issued_on": issued_on,
                             "due_on": "2026-12-30", "lines": [{"description": "x", "amount": "1000", "currency": "GBP"}]})
    assert Decimal(result["total"]) == Decimal("1000.00") + adjustments("RTM-NYC", "GBP", Decimal("1000.00"), issued_on)


@pytest.mark.parametrize("issued_on", BACK_DATES)
def test_invoice_lines_use_the_issue_date_not_the_due_date(cli, issued_on):
    result = cli("invoice", {"invoice_id": "I-1", "lane": "YOK-SIN", "currency": "GBP", "issued_on": issued_on,
                             "due_on": "2026-12-30", "lines": [{"description": "x", "amount": "5000", "currency": "SGD"}]})
    subtotal = cents(Decimal("5000") * spot("SGD", "GBP", issued_on))
    assert Decimal(result["total"]) == subtotal + adjustments("YOK-SIN", "GBP", subtotal, issued_on)


@pytest.mark.parametrize("settled_on", BACK_DATES)
def test_settlement_uses_the_settlement_date(cli, settled_on):
    result = cli("settlement", {"carrier": "C-1", "currency": "USD", "settled_on": settled_on,
                                "payables": [{"reference": "P-1", "amount": "7000", "currency": "EUR"}]})
    assert Decimal(result["total"]) == cents(Decimal("7000") * spot("EUR", "USD", settled_on))


@pytest.mark.parametrize("filed_on", BACK_DATES)
def test_declaration_uses_the_filing_date(cli, filed_on):
    result = cli("declaration", {"declaration_id": "D-1", "importing_currency": "EUR", "filed_on": filed_on,
                                 "items": [{"hs_code": "6204", "value": "900000", "currency": "JPY"}]})
    value = cents(Decimal("900000") * spot("JPY", "EUR", filed_on))
    assert Decimal(result["total"]) == cents(value * Decimal("12") / 100)


@pytest.mark.parametrize("assessed_on", BACK_DATES)
def test_claim_uses_the_assessment_date_not_the_incident(cli, assessed_on):
    result = cli("claim", {"claim_id": "CL-1", "amount": "2500", "currency": "SGD", "deductible_percent": "10",
                           "settlement_currency": "EUR", "assessed_on": assessed_on, "incident_on": "2026-01-15"})
    assert Decimal(result["total"]) == cents(Decimal("2250") * spot("SGD", "EUR", assessed_on))


@pytest.mark.parametrize("period_end", ["2026-03-31", "2026-06-30", "2026-09-30"])
def test_closing_uses_the_period_end(cli, period_end):
    result = cli("closing", {"reporting_currency": "JPY", "period_end": period_end,
                             "balances": [{"amount": "1000", "currency": "EUR"}, {"amount": "500", "currency": "GBP"}]})
    pivot = Decimal("1000") * spot("EUR", "USD", period_end) + Decimal("500") * spot("GBP", "USD", period_end)
    assert Decimal(result["total"]) == cents(pivot * spot("USD", "JPY", period_end))


def test_one_batch_with_several_dates(cli):
    """The overnight run handles many documents in one process, so nothing may carry a rate from one to the next."""
    def settlement(on):
        return {"kind": "settlement", "doc": {"carrier": "C-1", "currency": "USD", "settled_on": on,
                                              "payables": [{"reference": "P-1", "amount": "7000", "currency": "EUR"}]}}

    dates = ["2026-02-14", "2026-08-20", "2026-05-02", "2026-02-14"]
    results = cli("batch", [settlement(on) for on in dates])
    assert [Decimal(row["total"]) for row in results] == [cents(Decimal("7000") * spot("EUR", "USD", on)) for on in dates]


def test_mixed_batch_keeps_each_documents_date(cli):
    results = cli("batch", [
        {"kind": "quote", "doc": {"lane": "RTM-NYC", "tonnes": "40", "currency": "GBP", "booked_on": "2026-02-14"}},
        {"kind": "quote", "doc": {"lane": "RTM-NYC", "tonnes": "40", "currency": "GBP", "booked_on": "2026-08-20"}},
    ])
    assert [Decimal(row["total"]) for row in results] == [expected_quote("RTM-NYC", "40", "GBP", "2026-02-14"),
                                                          expected_quote("RTM-NYC", "40", "GBP", "2026-08-20")]


def test_berth_charge_is_untouched(cli):
    assert Decimal(cli("berth-charge", {"berth_class": "B", "hours": "12"})["total"]) == Decimal("5208.00")


def test_repository_suite_passes(py, tmp_path):
    report = tmp_path / "visible.xml"
    done = py("-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", timeout=55)
    assert report.exists(), done.stdout[-1500:] + done.stderr[-500:]
    cases = list(ET.parse(report).getroot().iter("testcase"))
    bad = [case.get("name") for case in cases if case.find("failure") is not None or case.find("error") is not None]
    skipped = [case.get("name") for case in cases if case.find("skipped") is not None]
    assert not bad, f"failing: {bad[:10]}"
    assert not skipped, f"skipped: {skipped[:10]}"
    assert len(cases) >= MIN_VISIBLE_TESTS, f"only {len(cases)} tests remain"


# ---- the contract and the type settings -------------------------------------------------------------------------


def read_ini(path: Path) -> configparser.ConfigParser:
    assert path.exists(), f"{path.name} is missing"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    return parser


def lines_of(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def contains_in_order(short: list[str], long: list[str]) -> bool:
    remaining = iter(long)
    return all(item in remaining for item in short)


@pytest.fixture(scope="module")
def contract_baseline():
    return read_ini(BASELINE / "importlinter.ini")


@pytest.fixture(scope="module")
def mypy_baseline():
    return read_ini(BASELINE / "mypy.ini")


@pytest.fixture(scope="module")
def modules(ws):
    """Dotted name to (is package, parsed tree) for every module in the package."""
    found = {}
    for path in sorted((ws / "tidewater").rglob("*.py")):
        parts = path.relative_to(ws).with_suffix("").parts
        is_package = parts[-1] == "__init__"
        found[".".join(parts[:-1] if is_package else parts)] = (is_package, path, ast.parse(path.read_text()))
    return found


def imports_of(name: str, is_package: bool, tree: ast.AST) -> set[str]:
    """Import-linter sees imports anywhere in a module. String-based imports with a literal target are held to the same rule."""
    targets = set()
    package = name.split(".") if is_package else name.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            prefix = ".".join([*base, *([node.module] if node.module else [])])
            targets.add(prefix)
            targets.update(f"{prefix}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            function = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if function in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                targets.add(node.args[0].value)
    return targets


def inside(module: str, container: str) -> bool:
    return module == container or module.startswith(container + ".")


def test_import_contract_not_relaxed(ws, contract_baseline):
    current = read_ini(ws / ".importlinter")
    for section in contract_baseline.sections():
        assert section in current, f"{section} was removed"
        for key, value in contract_baseline[section].items():
            if key == "layers":
                assert contains_in_order(lines_of(value), lines_of(current[section][key])), "the layers were changed"
            elif key == "modules":
                assert set(lines_of(value)) <= set(lines_of(current[section][key])), "modules left the contract"
            else:
                assert current[section].get(key, "").strip() == value.strip(), f"{key} was changed"
        added = set(current[section]) - set(contract_baseline[section])
        forbidden = {"ignore_imports", "exclude_type_checking_imports", "unmatched_ignore_imports_alerting"}
        assert not added & forbidden, f"{sorted(added & forbidden)} added to {section}"
    if (ws / "pyproject.toml").exists():
        tool = tomllib.loads((ws / "pyproject.toml").read_text()).get("tool", {})
        assert "importlinter" not in tool and "mypy" not in tool, "tool settings were added in pyproject.toml"


def test_imports_respect_the_layers(modules, contract_baseline):
    layers = lines_of(contract_baseline["importlinter:contract:layers"]["layers"])
    broken = []
    for name, (is_package, _, tree) in modules.items():
        own = next((i for i, layer in enumerate(layers) if inside(name, layer)), None)
        if own is None:
            continue
        for target in imports_of(name, is_package, tree):
            other = next((i for i, layer in enumerate(layers) if inside(target, layer)), None)
            if other is not None and other < own:
                broken.append(f"{name} imports {target}")
    assert not broken, f"layer contract broken: {broken[:8]}"


def test_domain_packages_stay_independent(modules, contract_baseline):
    independent = lines_of(contract_baseline["importlinter:contract:domain-independence"]["modules"])
    broken = []
    for name, (is_package, _, tree) in modules.items():
        own = next((package for package in independent if inside(name, package)), None)
        if own is None:
            continue
        for target in imports_of(name, is_package, tree):
            other = next((package for package in independent if inside(target, package)), None)
            if other not in {None, own}:
                broken.append(f"{name} imports {target}")
    assert not broken, f"independence contract broken: {broken[:8]}"


def test_type_settings_not_relaxed(ws, mypy_baseline):
    current = read_ini(ws / "mypy.ini")
    for section in mypy_baseline.sections():
        assert section in current, f"{section} was removed"
        for key, value in mypy_baseline[section].items():
            assert current[section].get(key, "").strip() == value.strip(), f"{section}: {key} was changed"
    lax = {"ignore_errors": "true", "follow_imports": "skip", "disallow_untyped_defs": "false",
           "disallow_incomplete_defs": "false", "disallow_any_explicit": "false", "warn_return_any": "false"}
    for section in current.sections():
        known = mypy_baseline[section] if section in mypy_baseline else {}
        for key, value in current[section].items():
            if key not in known and lax.get(key) == value.strip().lower():
                raise AssertionError(f"{section}: {key} = {value} loosens checking")


def strict_flags(name: str, baseline: configparser.ConfigParser) -> set[str]:
    flags = set()
    for section in baseline.sections():
        if section.startswith("mypy-") and fnmatch.fnmatch(name + ".", section[len("mypy-"):].replace(".*", ".*")):
            flags.update(key for key, value in baseline[section].items() if value.strip() == "True")
    return flags


def untyped_functions(tree: ast.AST) -> list[str]:
    missing = []

    def check(function, in_class):
        arguments = function.args
        params = [*arguments.posonlyargs, *arguments.args]
        decorated_static = any(getattr(d, "id", "") == "staticmethod" for d in function.decorator_list)
        if in_class and params and not decorated_static:
            params = params[1:]
        params += [*arguments.kwonlyargs, *filter(None, [arguments.vararg, arguments.kwarg])]
        unannotated = [p.arg for p in params if p.annotation is None]
        no_return = function.returns is None and not (function.name == "__init__" and params)
        if unannotated or no_return:
            missing.append(f"{function.name}({', '.join(unannotated)}){' no return type' if no_return else ''}")

    def walk(node, in_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                check(child, in_class)
                walk(child, False)
            else:
                walk(child, isinstance(child, ast.ClassDef))

    walk(tree, False)
    return missing


def test_strict_modules_stay_fully_annotated(modules, mypy_baseline):
    problems = []
    for name, (_, _, tree) in modules.items():
        if "disallow_untyped_defs" in strict_flags(name, mypy_baseline):
            problems += [f"{name}: {item}" for item in untyped_functions(tree)]
    assert not problems, f"untyped code in strict modules: {problems[:8]}"


def test_strict_modules_have_no_explicit_any(modules, mypy_baseline):
    problems = []
    for name, (_, _, tree) in modules.items():
        if "disallow_any_explicit" in strict_flags(name, mypy_baseline):
            for node in ast.walk(tree):
                if (isinstance(node, ast.Name) and node.id == "Any") or (isinstance(node, ast.Attribute) and node.attr == "Any"):
                    problems.append(name)
    assert not problems, f"explicit Any in strict modules: {sorted(set(problems))[:8]}"


def test_no_type_checking_suppressions(modules):
    found = []
    for name, (_, path, _) in modules.items():
        for token in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
            if token.type == tokenize.COMMENT and re.search(r"type:\s*ignore|mypy:\s*\S", token.string):
                found.append(f"{name}: {token.string}")
    assert not found, f"suppressions added: {found[:8]}"


# ---- how the work was done --------------------------------------------------------------------------------------


def test_read_a_targeted_fraction_of_the_tree(ws, tool_calls):
    """Generous on purpose: this only catches reading the bulk of the repository rather than searching it."""
    sources = {path.relative_to(ws).as_posix(): path.stat().st_size for path in (ws / "tidewater").rglob("*.py")}
    opened = set()
    for call in tool_calls:
        if call["name"] == "Read":
            found = re.search(r"(tidewater/[\w/.-]+\.py)$", str(call["input"].get("file_path", "")))
            if found:
                opened.add(found.group(1))
        elif call["name"] == "Bash":
            command = str(call["input"].get("command", ""))
            if re.search(r"\b(cat|head|tail|sed|awk|less|more|nl|bat)\b", command):
                opened.update(re.findall(r"tidewater/[\w/.-]+\.py", command))
    assert len(opened & set(sources)) <= 0.25 * len(sources), f"opened {len(opened & set(sources))} of {len(sources)} modules"
    shown = sum(len(call.get("result", "")) for call in tool_calls)
    assert shown <= 0.6 * sum(sources.values()), f"{shown} bytes of tool output against a {sum(sources.values())} byte package"
