"""Acceptance for adding a public function: behavior first, then names, docstring, comments, suppressions.

The function's name is the agent's to choose, so it's found through the package's `__all__`.
"""

import ast
import io
import json
import math
import re
import sys
import tokenize
import tomllib
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

BASELINE_ALL = {
    "HIGH_WATER", "LOW_WATER", "Constituent", "Reading", "TideEvent", "daily_extrema",
    "datum_correctors", "find_turning_points", "load_readings", "local_day", "mean_high_water",
    "mean_low_water", "mean_tidal_range", "predict_level_m", "principal_constituent",
    "reading_from_row", "readings_between", "readings_for_station", "reduce_to_chart_datum",
}
POSITIONAL_PARAMETERS = 6
STATION, TZ_NAME = "HLX", "America/Halifax"
# The requested station isn't the last one in the dict, on purpose.
OFFSETS_M = {"HLX": 0.35, "YRM": 1.1, "SYD": -0.2}
FIRST_DAY, LAST_DAY = date(2026, 7, 1), date(2026, 7, 4)

HISTORY_TOKEN = re.compile(
    r"^(v\d+|new|newer|old|older|legacy|updated|improved|revised|refactored|rewritten|fixed"
    r"|better|enhanced|modified|alt|redux|replacement)$"
)
OFF_VOCABULARY = {
    "site", "sites", "location", "locations", "height", "heights", "peak", "peaks", "trough",
    "troughs", "sample", "samples", "measurement", "measurements", "observation", "observations",
    "highs", "lows",
}
NARRATING = re.compile(
    r"^#\s*(now\b|first\b|next\b|then\b|finally\b|step\s*\d|loop\b|iterate\b|initiali[sz]e\b"
    r"|create\b|build\b|get\b|fetch\b|compute\b|calculate\b|convert\b|filter\b|sort\b|group\b"
    r"|add\b|append\b|return\b|check\b|import\b|set up\b|call\b|store\b|walk\b|go through\b"
    r"|for each\b|reduce\b|find\b|bucket\b|select\b)",
    re.I,
)
GIVES_A_REASON = re.compile(
    r"\b(because|since|so that|otherwise|unless|avoid|keep|without|even though|must|only|cannot"
    r"|not)\b|n.t\b|[:—]| -- ",
    re.I,
)
HISTORY_COMMENT = re.compile(
    r"\b(previously|used to|no longer|formerly|changed (from|to)|replaces?|replaced|added (for|in|to)"
    r"|new (function|module|helper|version|in)|moved from|refactor(ed)?|old (way|code|version)"
    r"|originally|now uses?|instead of the old|unlike the old)\b",
    re.I,
)
SUPPRESSION = re.compile(r"#\s*(noqa\b|type:\s*ignore\b|pyright:\s*ignore\b|(ruff|flake8)\s*:\s*noqa\b)", re.I)
SCOPED = re.compile(r"#\s*(noqa\s*:\s*[A-Z]+\d+|(type|pyright):\s*ignore\s*\[)", re.I)
CODES = re.compile(r"#\s*((?i:noqa)\s*:\s*[A-Za-z]+\d+(?:[,\s]+[A-Z]+\d+)*|(?:type|pyright):\s*ignore\s*\[[^\]]*\])")

CALL_FUNCTION = r"""
import json, sys
from datetime import UTC, date, datetime
import tidekit

spec = json.load(sys.stdin)
readings = [tidekit.Reading(s, datetime.fromisoformat(t), l) for s, t, l in spec["readings"]]
result = getattr(tidekit, spec["name"])(
    spec["station"], readings, spec["offsets"], spec["tz"],
    date.fromisoformat(spec["first"]), date.fromisoformat(spec["last"]),
)
assert isinstance(result, dict), type(result)
out = {}
for day, events in result.items():
    assert type(day) is date, day
    assert isinstance(events, list), type(events)
    rows = []
    for event in events:
        assert isinstance(event, tidekit.TideEvent), event
        rows.append([event.station, event.kind, event.occurred_at.astimezone(UTC).isoformat(), event.level_m])
    out[day.isoformat()] = rows
print(json.dumps(out))
"""
DESCRIBE_EXPORTS = r"""
import inspect, json, tidekit

out = {"all": list(tidekit.__all__), "functions": {}}
for name in tidekit.__all__:
    item = getattr(tidekit, name)
    if inspect.isfunction(item):
        parameters = inspect.signature(item).parameters.values()
        out["functions"][name] = {
            "parameters": [p.name for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)],
            "annotated": all(p.annotation is not p.empty for p in parameters)
                and inspect.signature(item).return_annotation is not inspect.Signature.empty,
            "module": item.__module__,
            "doc": inspect.getdoc(item) or "",
        }
print(json.dumps(out))
"""
RUN_EXAMPLES = r"""
import doctest, importlib, json, sys
import tidekit

function = getattr(tidekit, sys.argv[1])
module = importlib.import_module(function.__module__)
runner = doctest.DocTestRunner(verbose=False)
report = []
tests = doctest.DocTestFinder(recurse=False).find(function, function.__name__, module=module, globs=dict(vars(module)))
for test in tests:
    runner.run(test, out=report.append)
results = runner.summarize(verbose=False)
print(json.dumps({"attempted": results.attempted, "failed": results.failed, "report": "".join(report)}))
"""


def readings_for_test():
    """Three stations, in time order: a semidiurnal tide sampled every 20 minutes."""
    rows = []
    start = datetime(2026, 6, 30, tzinfo=UTC)
    for step in range(5 * 72):
        at = start + timedelta(minutes=20 * step)
        hours = step / 3
        for code, phase in ((STATION, 0.7), ("YRM", 1.9), ("SYD", 3.1)):
            level = 2.0 + 1.5 * math.cos(2 * math.pi * hours / 12.42 + phase)
            rows.append([code, at.isoformat(), level])
    return rows


def expected_events():
    """Worked out here rather than through the repository's helpers."""
    series = [row for row in readings_for_test() if row[0] == STATION]
    days = {}
    for before, row, after in zip(series, series[1:], series[2:], strict=False):
        if before[2] < row[2] > after[2]:
            kind = "high_water"
        elif before[2] > row[2] < after[2]:
            kind = "low_water"
        else:
            continue
        at = datetime.fromisoformat(row[1])
        days.setdefault(at.astimezone(ZoneInfo(TZ_NAME)).date(), []).append(
            [STATION, kind, at.isoformat(), row[2] - OFFSETS_M[STATION]]
        )
    return days


def day_range(first, last):
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


@pytest.fixture(scope="session")
def exports(py):
    done = py("-c", DESCRIBE_EXPORTS)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="session")
def added(exports):
    candidates = {
        name: info
        for name, info in exports["functions"].items()
        if name not in BASELINE_ALL and len(info["parameters"]) == POSITIONAL_PARAMETERS
    }
    assert len(candidates) == 1, f"expected one new exported function taking six arguments: {sorted(candidates)}"
    name, info = next(iter(candidates.items()))
    return {"name": name, **info}


@pytest.fixture(scope="session")
def calendar_output(py, added):
    def run(first, last):
        spec = {
            "name": added["name"], "station": STATION, "readings": readings_for_test(), "offsets": OFFSETS_M,
            "tz": TZ_NAME, "first": first.isoformat(), "last": last.isoformat(),
        }
        done = py("-c", CALL_FUNCTION, input=json.dumps(spec))
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run


@pytest.fixture(scope="session")
def base(git):
    """The starter's HEAD: its second commit, whatever the agent committed on top."""
    return git("rev-list", "--reverse", "HEAD").split()[1]


@pytest.fixture(scope="session")
def added_paths(git, base):
    committed = git("diff", "--name-only", "--diff-filter=A", base).splitlines()
    return sorted(set(committed) | set(git("ls-files", "--others", "--exclude-standard").splitlines()))


@pytest.fixture(scope="session")
def package_python(git, base, added_paths):
    """New or changed Python files in the package, with their starting text ('' for a new file)."""
    changed = git("diff", "--name-only", "--diff-filter=M", base).splitlines()
    files = {}
    for path in changed:
        if path.startswith("tidekit/") and path.endswith(".py"):
            files[path] = git("show", f"{base}:{path}")
    for path in added_paths:
        if path.startswith("tidekit/") and path.endswith(".py"):
            files[path] = ""
    return files


def comments_in(source):
    return [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]


def new_comments(ws, package_python):
    """Comments that weren't in the starter, as (path, line, text, whole file's lines)."""
    found = []
    for path, before in package_python.items():
        source = (ws / path).read_text()
        known = [text for _, text in comments_in(before)]
        for line, text in comments_in(source):
            if text in known:
                known.remove(text)
            else:
                found.append((path, line, text, source.splitlines()))
    return found


def names_defined(source):
    """Function, class, parameter and local variable names in a module."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def definition_names(source):
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_every_day_in_the_range_is_listed(calendar_output):
    days = calendar_output(FIRST_DAY, LAST_DAY)
    assert sorted(days) == [day.isoformat() for day in day_range(FIRST_DAY, LAST_DAY)]


def test_a_day_with_nothing_is_an_empty_list(calendar_output):
    days = calendar_output(date(2026, 6, 26), date(2026, 6, 28))
    assert days == {"2026-06-26": [], "2026-06-27": [], "2026-06-28": []}


def test_events_fall_on_local_days_in_time_order(calendar_output):
    expected = expected_events()
    moved = [
        event
        for day, events in expected.items()
        for event in events
        if datetime.fromisoformat(event[2]).date() != day
    ]
    assert moved, "the test data must include an event whose UTC date differs from its local one"
    days = calendar_output(FIRST_DAY, LAST_DAY)
    for day in day_range(FIRST_DAY, LAST_DAY):
        got = [event[:3] for event in days[day.isoformat()]]
        assert got == [event[:3] for event in expected.get(day, [])], day


def test_levels_are_relative_to_chart_datum(calendar_output):
    expected = expected_events()
    days = calendar_output(FIRST_DAY, LAST_DAY)
    for day in day_range(FIRST_DAY, LAST_DAY):
        got = [event[3] for event in days[day.isoformat()]]
        assert got == pytest.approx([event[3] for event in expected.get(day, [])]), day


def test_existing_exports_are_kept(exports):
    assert BASELINE_ALL <= set(exports["all"])


def test_daily_extrema_is_left_alone(ws, git, base):
    def extrema(source):
        tree = ast.parse(source)
        return next(ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "daily_extrema")

    assert extrema((ws / "tidekit" / "summary.py").read_text()) == extrema(git("show", f"{base}:tidekit/summary.py"))


def test_visible_suite_passes(py):
    done = py("-m", "pytest", "-q", "-p", "no:cacheprovider", timeout=50)
    assert done.returncode == 0, done.stdout


def test_existing_tests_are_not_weakened(ws, git, base):
    def functions(source):
        return {n.name: ast.dump(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}

    for path in git("ls-tree", "-r", "--name-only", base, "tests/").splitlines():
        assert (ws / path).exists(), f"{path} was deleted"
        before, after = functions(git("show", f"{base}:{path}")), functions((ws / path).read_text())
        changed = [name for name, body in before.items() if after.get(name) != body]
        assert not changed, f"changed or removed in {path}: {changed}"


def test_lint_passes(py):
    done = py("-m", "ruff", "check", "--no-cache", ".")
    assert done.returncode == 0, done.stdout


def test_package_doctests_pass(py):
    done = py("-m", "pytest", "-q", "-p", "no:cacheprovider", "--doctest-modules", "tidekit", timeout=50)
    assert done.returncode == 0, done.stdout


def test_gates_are_not_weakened(ws, git, base):
    before = tomllib.loads(git("show", f"{base}:pyproject.toml")).get("tool", {})
    after = tomllib.loads((ws / "pyproject.toml").read_text()).get("tool", {})
    assert after.get("ruff") == before.get("ruff"), "the lint configuration was changed"
    assert after.get("pytest") == before.get("pytest"), "the pytest configuration was changed"
    assert (ws / "check.sh").read_text() == git("show", f"{base}:check.sh"), "check.sh was changed"
    assert not (ws / "ruff.toml").exists() and not (ws / ".ruff.toml").exists(), "a new lint configuration was added"


def test_each_station_keeps_its_own_offset(py):
    code = (
        "from tidekit import datum_correctors\n"
        "correctors = datum_correctors({'A': 1.0, 'B': 2.0, 'C': 4.0})\n"
        "print([correctors[s](10.0) for s in 'ABC'])\n"
    )
    done = py("-c", code)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [9.0, 8.0, 6.0]


def test_no_bare_suppressions(ws, git):
    paths = set(git("ls-files", "*.py").splitlines())
    paths |= {p for p in git("ls-files", "--others", "--exclude-standard").splitlines() if p.endswith(".py")}
    bare = [
        f"{path}:{line}: {text}"
        for path in sorted(paths)
        if (ws / path).exists()
        for line, text in comments_in((ws / path).read_text())
        if SUPPRESSION.search(text) and not SCOPED.search(text)
    ]
    assert not bare, f"suppressions that hide every rule on the line: {bare}"


def test_new_suppressions_are_explained(ws, package_python):
    unexplained = []
    for path, line, text, lines in new_comments(ws, package_python):
        if not SCOPED.search(text):
            continue
        reason = CODES.sub("", text)
        said_inline = len(re.findall(r"[A-Za-z]{2,}", reason)) >= 2
        neighbours = [lines[n].strip() for n in (line - 2, line) if 0 <= n < len(lines)]
        said_nearby = any(n.startswith("#") and len(n.split()) >= 4 for n in neighbours)
        if not (said_inline or said_nearby):
            unexplained.append(f"{path}:{line}: {text}")
    assert not unexplained, f"suppressions with no reason given: {unexplained}"


def test_no_module_shadows_the_standard_library(added_paths):
    shadows = [
        path
        for path in added_paths
        if path.endswith(".py") and path.rsplit("/", 1)[-1][:-3] in sys.stdlib_module_names
    ]
    assert not shadows, f"named after a standard library module: {shadows}"


def test_nightly_job_still_runs_as_a_script(py):
    done = py(
        "tidekit/nightly.py", "--export", "data/harbour-export.csv", "--offsets", "data/datum_offsets.json",
        "--day", "2026-07-02",
    )
    assert done.returncode == 0, done.stderr
    assert re.search(r"^HLX ", done.stdout, re.M)


def test_no_history_in_names(ws, added, added_paths, package_python):
    names = {added["name"], *added["parameters"]}
    names |= {path.rsplit("/", 1)[-1][:-3] for path in added_paths if path.endswith(".py")}
    for path, before in package_python.items():
        names |= definition_names((ws / path).read_text()) - definition_names(before or "")
    historic = sorted(n for n in names if any(HISTORY_TOKEN.match(t) for t in n.lower().split("_")))
    assert not historic, f"names that describe the change rather than the thing: {historic}"


def test_names_follow_the_vocabulary(ws, added, package_python):
    names = {added["name"], *added["parameters"]}
    for path, before in package_python.items():
        names |= names_defined((ws / path).read_text()) - names_defined(before or "")
    off = sorted(n for n in names if OFF_VOCABULARY & set(n.lower().split("_")))
    assert not off, f"names that don't use the package's vocabulary: {off}"
    for position, word in enumerate(("station", "reading", "offset")):
        assert word in added["parameters"][position], f"{added['parameters'][position]}: the package calls this {word}"


def test_docstring_is_numpy_style(ws, added):
    doc = added["doc"]
    assert doc, "no docstring"
    assert not re.search(r"^\s*(Args|Arguments|Parameters|Returns?|Yields?|Raises|Examples?|Attributes):\s*$", doc, re.M), "section headers in another style"
    assert not re.search(r":param\b|:returns?:|:rtype:|@param\b", doc), "field lists in another style"
    sections = re.findall(r"^(\S[^\n]*)\n(-{3,})\s*$", doc, re.M)
    assert all(len(title.strip()) == len(rule) for title, rule in sections), f"underlines: {sections}"
    titles = [title.strip() for title, _ in sections]
    for needed in ("Parameters", "Returns", "Examples"):
        assert needed in titles, f"no {needed} section"

    block = re.search(r"^Parameters\n-+\n(.*?)(?=^\S[^\n]*\n-{3,}\s*$|\Z)", doc, re.M | re.S).group(1)
    described = set()
    for line in block.splitlines():
        if line.strip() and not line.startswith((" ", "\t")):
            described |= {name.strip().lstrip("*") for name in line.split(":")[0].split(",")}
    missing = [name for name in added["parameters"] if name not in described]
    assert not missing, f"parameters not described: {missing}"

    module_path = ws / (added["module"].replace(".", "/") + ".py")
    function = next(
        node for node in ast.walk(ast.parse(module_path.read_text()))
        if isinstance(node, ast.FunctionDef) and node.name == added["name"]
    )
    if any(isinstance(node, ast.Raise) for node in ast.walk(function)):
        assert "Raises" in titles, "raises without a Raises section"


def test_docstring_examples_run(py, added):
    assert "+SKIP" not in added["doc"], "examples must actually run"
    done = py("-c", RUN_EXAMPLES, added["name"])
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["attempted"] >= 1, "no runnable examples"
    assert result["failed"] == 0, result["report"]


def test_signature_is_annotated(added):
    assert added["annotated"], "the package annotates every signature"


def test_no_narrating_comments(ws, package_python):
    narrating = [
        f"{path}:{line}: {text}"
        for path, line, text, _ in new_comments(ws, package_python)
        if not SUPPRESSION.search(text) and NARRATING.search(text) and not GIVES_A_REASON.search(text)
    ]
    assert len(narrating) < 2, f"comments restating the code: {narrating}"


def test_no_history_in_comments(ws, package_python):
    historic = [
        f"{path}:{line}: {text}"
        for path, line, text, _ in new_comments(ws, package_python)
        if HISTORY_COMMENT.search(text)
    ]
    assert not historic, f"comments about the change rather than the code: {historic}"
