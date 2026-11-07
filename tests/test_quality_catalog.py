"""docs/quality-catalog.md maps 500 failure modes to occam's mechanisms. This checks its claims against the code, so a removed
check can't stay listed, and checks that what was added for it can't send an agent back, per DESIGN.md's no-new-send-backs.

It shows the mechanisms exist. It says nothing about whether they help: see docs/evaluation.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

from occam_tools import change_checks, scan  # noqa: E402
from occam_tools.catalog import BY_ID  # noqa: E402
from rule_cases_quality import QUALITY_CASES, SEVERITY, STDLIB_NEAR_MISSES  # noqa: E402
from rule_cases_resources import CONFIG_CASES, RESOURCE_CASES, SECRET_CASES  # noqa: E402
from rule_cases_js import JS_CASES  # noqa: E402
from scan_notes import _is_serious  # noqa: E402
from test_change_checks import notes_on, repository, write  # noqa: E402

DOCUMENT = (ROOT / "docs" / "quality-catalog.md").read_text()
LARGE = (ROOT / "docs" / "large-codebase-failures.md").read_text()
ROW = re.compile(r"^\| (F\d{3}) \| (P[012]) \| (.+?) \| ([^|]*?) \| ([^|]*?) \| (strong|partial|none) \| ([^|]*?) \| (.*) \|$", re.M)
ROWS = ROW.findall(DOCUMENT)
OWN = re.compile(r"^\| ((?:guide|gate|note|hook):[\w-]+) \| (\S+) \| (`+) ?(.*?) ?\3 \|$", re.M)
MECHANISMS = {token: (path, phrase) for token, path, _, phrase in OWN.findall(DOCUMENT)}
LARGE_MECHANISMS = set(re.findall(r"^\| ((?:hook|note|gate|guide):[\w-]+) \| .+? \| \S+ \| `.+` \|$", LARGE, re.M))
NEW_RULES = {"loop-variable-closure", "mutated-while-iterating", "shared-class-mutable", "swallowed-cancellation", "salted-hash-partition", "wall-clock-wait",
             "stdlib-shadowed", "unwrapped-decorator", "gpu-timing-unsynced", "async-predicate", "unsafe-undocumented", "equals-without-hashcode",
             "nan-comparison", "nested-event-loop", "process-pool-unpicklable", "compile-in-loop", "ctypes-untyped", "check-then-insert",
             "retry-not-idempotent", "webhook-unverified", "error-details-exposed"}
# Added in a second pass for the rows still partial. private-import is cross-file, so its cases are in test_scanner_rules.PROJECT.
MORE_RULES = {"mock-assert-typo", "lazy-after-close", "await-under-thread-lock", "lock-order", "cache-reads-user", "client-per-call", "io-in-property",
              "unbounded-queue", "nonatomic-state-write", "network-in-unit-test", "fixed-test-resource", "unseeded-random-test", "dense-comprehension",
              "range-len-loop", "mock-of-subject", "dead-control", "formatter-conflict", "live-credential-in-test"}
LEVELS = {"stops": "Stops it or sends it back", "forces": "Forces a step that can catch it", "finds": "Finds it", "says": "Says it at the moment",
          "tool": "A tool answers it, if run", "guide": "Guidance and tracking only", "nothing": "Nothing"}
FORCES_A_STEP = {"hook:check-after-edit", "hook:review-required", "hook:scan-at-stop", "hook:audit-at-stop"}
ASKS_ONLY = {"gate:judgment", "gate:scope", "gate:size"}
TRACKS_ONLY = {"tool:goal", "tool:coord", "tool:gate", "tool:design", "tool:partition"}


def tokens_of(row) -> list[str]:
    return [token for token in (*row[3].split(), *row[4].split()) if token != "none"]


def level_of(tokens: list[str]) -> str:
    if not tokens:
        return "nothing"
    if any(token.startswith("hook:") and token not in FORCES_A_STEP for token in tokens):
        return "stops"
    if any(token in FORCES_A_STEP for token in tokens):
        return "forces"
    if any(token.startswith(("scan:", "gate:")) and token not in ASKS_ONLY for token in tokens):
        return "finds"
    if any(token.startswith("note:") or token in ASKS_ONLY for token in tokens):
        return "says"
    if any(token.startswith(("query:", "tool:")) and token not in TRACKS_ONLY for token in tokens):
        return "tool"
    return "guide"


def commands(*args) -> set[str]:
    done = subprocess.run([sys.executable, str(ROOT / "plugin/skills/occam/scripts/occam.py"), *args, "--help"], capture_output=True, text=True, timeout=60, check=True)
    return {word.strip() for found in re.findall(r"\{([\w,-]+)\}", done.stdout) for word in found.split(",")}


def test_it_lists_the_500_once_in_order_with_the_reports_tiers():
    assert [row[0] for row in ROWS] == [f"F{number:03d}" for number in range(1, 501)]
    assert Counter(row[1] for row in ROWS) == {"P0": 65, "P1": 426, "P2": 9}


def test_every_scan_rule_named_is_a_real_rule():
    named = {token[5:] for row in ROWS for token in tokens_of(row) if token.startswith("scan:")}
    assert named and not named - set(BY_ID)


def test_every_query_and_tool_named_is_a_real_command():
    tokens = {token for row in ROWS for token in tokens_of(row)}
    assert {token[6:] for token in tokens if token.startswith("query:")} <= commands("query")
    assert {token[5:] for token in tokens if token.startswith("tool:")} <= commands()


def test_every_other_token_is_listed_with_where_it_lives():
    tokens = {token for row in ROWS for token in tokens_of(row) if token.startswith(("hook:", "note:", "gate:", "guide:"))}
    assert not tokens - LARGE_MECHANISMS - set(MECHANISMS)
    assert not set(MECHANISMS) & LARGE_MECHANISMS, "a token defined in both catalogs"


@pytest.mark.parametrize("token", sorted(MECHANISMS))
def test_each_mechanism_named_here_is_where_this_says(token):
    path, phrase = MECHANISMS[token]
    assert phrase in (ROOT / path).read_text(), f"{token}: {phrase!r} is gone from {path}. Update the catalog, since what it claims may no longer hold."


def test_the_counts_at_the_top_match_the_rows():
    levels = Counter(level_of(tokens_of(row)) for row in ROWS)
    p0 = Counter(level_of(tokens_of(row)) for row in ROWS if row[1] == "P0")
    for level, name in LEVELS.items():
        assert re.search(rf"^\| {re.escape(name)} \| {levels[level]} \| {p0[level]} \|", DOCUMENT, re.M), f"{name} should say {levels[level]} and {p0[level]}"
    fits = Counter(row[5] for row in ROWS)
    assert f"{fits['strong']} strong, {fits['partial']} partial, {fits['none']} none." in DOCUMENT


def test_each_area_row_adds_up():
    areas = re.findall(r"^\| \[[^\]]+\]\(#[^)]+\) \| (F\d{3})–(F\d{3}) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", DOCUMENT, re.M)
    assert len(areas) == 25
    for first, last, total, strong, partial, none in areas:
        fits = Counter(row[5] for row in ROWS if first <= row[0] <= last)
        assert (int(total), int(strong), int(partial), int(none)) == (sum(fits.values()), fits["strong"], fits["partial"], fits["none"]), first


def test_rows_that_arent_strong_say_whats_missing():
    assert not [row[0] for row in ROWS if row[5] != "strong" and row[7].strip() in ("", "-")]


def test_still_open_lists_exactly_the_p0_rows_that_arent_strong():
    section = DOCUMENT.split("## Still open", 1)[1].split("\n## ", 1)[0]
    listed = re.findall(r"^\| (F\d{3}) \|", section, re.M)
    assert listed == [row[0] for row in ROWS if row[1] == "P0" and row[5] != "strong"]


def test_the_new_rules_are_in_the_catalog_and_have_cases():
    assert NEW_RULES | MORE_RULES | {"private-import"} <= set(BY_ID)
    assert NEW_RULES <= {case[0] for case in QUALITY_CASES}
    assert MORE_RULES <= {case[0] for case in ADDED_CASES}


ADDED_CASES = [*QUALITY_CASES, *RESOURCE_CASES, *JS_CASES, *CONFIG_CASES, *SECRET_CASES]


@pytest.mark.parametrize("rule, path, positive, negative", ADDED_CASES, ids=[f"{case[0]}-{index}" for index, case in enumerate(ADDED_CASES)])
def test_nothing_added_for_the_catalog_sends_an_agent_back(rule, path, positive, negative):
    """New checks warn in scan and gate. A serious finding would send the agent back at Stop, which DESIGN.md's no-new-send-backs rules out."""
    found = [finding for finding in scan.scan_text(path, positive) if finding["rule"] == rule]
    assert found
    assert not [finding for finding in found if _is_serious({**finding, "id": finding.get("id", ""), "path": path})], f"{rule} would send the agent back"


@pytest.mark.parametrize("rule, path, text, severity", SEVERITY, ids=[f"{case[0]}-{index}" for index, case in enumerate(SEVERITY)])
def test_an_access_check_assert_is_reported_higher_than_other_asserts(rule, path, text, severity):
    assert [finding["severity"] for finding in scan.scan_text(path, text) if finding["rule"] == rule] == [severity]


@pytest.mark.parametrize("path", STDLIB_NEAR_MISSES)
def test_a_stdlib_name_only_matters_where_scripts_run(path):
    assert not [finding for finding in scan.scan_text(path, "def pick():\n    return 4\n") if finding["rule"] == "stdlib-shadowed"]


GATE_CASES = [
    ("memory-safety-added", {"src/lib.rs": "pub fn first(v: &[u8]) -> u8 {\n    v[0]\n}\n"},
     {"src/lib.rs": "pub fn first(v: &[u8]) -> u8 {\n    unsafe { *v.get_unchecked(0) }\n}\n"},
     {"src/lib.rs": "pub fn first(v: &[u8]) -> u8 {\n    v.first().copied().unwrap_or(0)\n}\n"}),
    ("memory-safety-added", {"fast.pyx": "def total(double[:] xs):\n    return sum(xs)\n"},
     {"fast.pyx": "cimport cython\n@cython.boundscheck(False)\ndef total(double[:] xs):\n    return sum(xs)\n"},
     {"fast.pyx": "cimport cython\n# boundscheck(False) would be faster, but the index comes from the caller\ndef total(double[:] xs):\n    return sum(xs)\n"}),
    ("checks-relaxed", {"pyproject.toml": "[tool.ruff.lint]\nselect = [\"E\", \"F\"]\n", "a.py": "x = 1\n"},
     {"pyproject.toml": "[tool.ruff.lint]\nselect = [\"E\", \"F\"]\nignore = [\"F401\"]\n"},
     {"pyproject.toml": "[tool.ruff.lint]\nselect = [\"E\", \"F\", \"B\"]\n"}),
    # Adding a code to a multi-line select list makes the check stricter, and a package-finding exclude isn't a check at all.
    ("checks-relaxed", {"pyproject.toml": "[tool.ruff.lint]\nselect = [\n    \"E\",\n]\n", "a.py": "x = 1\n"},
     {"pyproject.toml": "[tool.ruff.lint]\nselect = [\n    \"E\",\n]\nignore = [\n    \"E501\",\n]\n"},
     {"pyproject.toml": "[tool.ruff.lint]\nselect = [\n    \"E\",\n    \"B006\",\n]\n\n[tool.setuptools.packages.find]\nexclude = [\"tests\"]\n"}),
    ("checks-relaxed", {"tsconfig.json": "{\n  \"compilerOptions\": {\n    \"strict\": true\n  }\n}\n", "a.ts": "export const x = 1;\n"},
     {"tsconfig.json": "{\n  \"compilerOptions\": {\n    \"strict\": false\n  }\n}\n"},
     {"tsconfig.json": "{\n  \"compilerOptions\": {\n    \"strict\": true,\n    \"target\": \"es2022\"\n  }\n}\n"}),
    ("precision-lowered", {"model.py": "import torch\nx = torch.ones(3)\n"},
     {"model.py": "import torch\nx = torch.ones(3).half()\n"},
     {"model.py": "import torch\nx = torch.ones(3).double()\n"}),
    # review: switching lower precision off, or checking a dtype, lowers nothing
    ("precision-lowered", {"model.py": "import torch\nx = torch.ones(3)\n"},
     {"model.py": "import torch\nwith torch.autocast('cuda'):\n    x = torch.ones(3)\n"},
     {"model.py": "import torch\ntorch.backends.cuda.matmul.allow_tf32 = False\nif x.dtype == torch.float16:\n    x = x.float()\nwith torch.autocast('cuda', enabled=False):\n    x = torch.ones(3)\n"}),
    # review2: removing an exemption, a false, a per-module override and a camelCase eslint option aren't new exemptions
    ("checks-relaxed", {"pyproject.toml": "[tool.ruff.lint]\nignore = [\"E501\", \"F401\"]\n\n[tool.mypy]\nstrict = true\n", "a.py": "x = 1\n"},
     {"pyproject.toml": "[tool.ruff.lint]\nignore = [\"E501\", \"F401\", \"B008\"]\n\n[tool.mypy]\nstrict = true\n"},
     {"pyproject.toml": "[tool.ruff.lint]\nignore = [\"E501\"]\n\n[tool.mypy]\nstrict = true\nignore_missing_imports = false\n\n[[tool.mypy.overrides]]\nmodule = \"legacy.*\"\nignore_errors = true\n"}),
    ("checks-relaxed", {".eslintrc.json": "{\n  \"rules\": {\n    \"no-console\": \"error\"\n  }\n}\n", "a.js": "x = 1;\n"},
     {".eslintrc.json": "{\n  \"rules\": {\n    \"no-console\": \"off\"\n  }\n}\n"},
     {".eslintrc.json": "{\n  \"rules\": {\n    \"no-console\": \"error\",\n    \"indent\": [\"error\", 2]\n  },\n  \"settings\": {\n    \"tabWidth\": 0\n  }\n}\n"}),
    # review2: -fno-sanitize-recover makes a sanitizer build stricter, and a Rust string isn't an unsafe block
    ("memory-safety-added", {"CMakeLists.txt": "project(x)\n", "src/lib.rs": "pub fn f() {}\n"},
     {"CMakeLists.txt": "project(x)\nset(CMAKE_C_FLAGS \"-fno-sanitize=undefined\")\n"},
     {"CMakeLists.txt": "project(x)\nset(CMAKE_C_FLAGS \"-fsanitize=address -fno-sanitize-recover=all\")\n", "src/lib.rs": "pub fn f() -> &'static str {\n    \"unsafe { not code }\"\n}\n"}),
    # review2: a flag check, a dtype map and an import don't lower anything
    ("precision-lowered", {"train.py": "import torch\n"},
     {"train.py": "import torch\nmodel = model.to(torch.bfloat16)\n"},
     {"train.py": "import torch\nfrom torch.cuda.amp import autocast\nDTYPES = {'fp16': torch.float16, 'bf16': torch.bfloat16}\nif args.bf16:\n    log('bf16 requested')\n"}),
    # review3: mypy's per-module sections are already narrow
    ("checks-relaxed", {"mypy.ini": "[mypy]\nstrict = True\n", "a.py": "x = 1\n"},
     {"mypy.ini": "[mypy]\nstrict = True\nignore_missing_imports = True\n"},
     {"mypy.ini": "[mypy]\nstrict = True\n\n[mypy-yaml.*]\nignore_missing_imports = True\n"}),
    # review3: Decimal.quantize rounds money, and Hugging Face loads in fp16 through torch_dtype
    ("precision-lowered", {"m.py": "import torch\n"},
     {"m.py": "import torch\nmodel = AutoModel.from_pretrained(name, torch_dtype=torch.float16)\n"},
     {"m.py": "from decimal import Decimal, ROUND_HALF_UP\ntotal = (price * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)\n"}),
    # review: a Python docstring naming memcpy isn't native code
    ("memory-safety-added", {"native.c": "int f(void) { return 0; }\n", "wrap.py": "x = 1\n"},
     {"native.c": "#include <string.h>\nint f(char *d, char *s) { memcpy(d, s, 8); return 0; }\n"},
     {"wrap.py": "def copy(dst, src):\n    \"\"\"Like memcpy(dst, src, n), but checked.\"\"\"\n    dst[:] = src\n"}),
]


@pytest.mark.parametrize("rule, base, bad, near_miss", GATE_CASES, ids=[f"{case[0]}-{index}" for index, case in enumerate(GATE_CASES)])
def test_each_new_gate_note_speaks_on_the_bad_change_and_not_its_near_miss(rule, base, bad, near_miss, tmp_path):
    root = repository(tmp_path / "bad", base)
    write(root, bad)
    found, not_run = notes_on(root)
    assert rule in {note["rule"] for note in found}, (found, not_run)
    assert not not_run
    other = repository(tmp_path / "near", base)
    write(other, near_miss)
    assert rule not in {note["rule"] for note in notes_on(other)[0]}


def test_an_eslint_rule_name_full_of_slashes_stays_fast():
    """review3: the pattern once had nested repeats that went cubic on a long run of slashes."""
    started = time.monotonic()
    change_checks._exemptions(".eslintrc.json", '{"' + "a/" * 3000 + '": "warn"}\n')
    assert time.monotonic() - started < 1


def test_the_new_gate_notes_run_within_the_diff():
    """They read only the diff, so they stay true on a partial read and cost no searches."""
    assert {change_checks._memory_safety_added, change_checks._checks_relaxed, change_checks._precision_lowered} <= set(change_checks.WITHIN_THE_DIFF)
