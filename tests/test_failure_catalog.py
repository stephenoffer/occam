"""docs/large-codebase-failures.md claims occam has a mechanism for each failure. This checks those claims against the code, so a removed check can't stay listed.

It shows the mechanisms exist. It says nothing about whether they help: see docs/evaluation.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools.catalog import BY_ID  # noqa: E402

DOCUMENT = (ROOT / "docs" / "large-codebase-failures.md").read_text()
ROW = re.compile(r"^\| ([A-Z]+-\d{2,3}) \| (.+?) \| (.+?) \| ([^|]*?) \| ([^|]*?) \|$", re.M)
ROWS = ROW.findall(DOCUMENT)
MECHANISM = re.compile(r"^\| ((?:hook|note|gate|guide):[\w-]+) \| (.+?) \| (\S+) \| `(.+)` \|$", re.M)
MECHANISMS = {token: (path, proof) for token, _, path, proof in MECHANISM.findall(DOCUMENT)}
FORCES_A_STEP = {"hook:check-after-edit", "hook:review-required", "hook:scan-at-stop", "hook:audit-at-stop"}
ASKS_ONLY = {"gate:judgment", "gate:scope", "gate:size"}
TRACKS_ONLY = {"tool:goal", "tool:coord", "tool:gate", "tool:design", "tool:partition"}
LEVEL_NAMES = {"stops": "Stops it or sends it back", "forces": "Forces a step that can catch it", "finds": "Finds it", "says": "Says it at the moment", "tool": "A tool answers it, if run", "guide": "Guidance and tracking only"}


def tokens_of(row) -> list[str]:
    return [token for token in (*row[3].split(), *row[4].split()) if token != "none"]


def level_of(tokens: list[str]) -> str:
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
    """The subcommands `occam` really offers, read from its own help."""
    done = subprocess.run([sys.executable, str(ROOT / "plugin/skills/occam/scripts/occam.py"), *args, "--help"], capture_output=True, text=True, timeout=60, check=True)
    return {word.strip() for found in re.findall(r"\{([\w,-]+)\}", done.stdout) for word in found.split(",")}


def test_it_lists_more_than_300_distinct_failures():
    assert len(ROWS) >= 300
    assert len({row[0] for row in ROWS}) == len(ROWS), "duplicate id"
    texts = Counter(row[1].lower() for row in ROWS)
    assert not [text for text, count in texts.items() if count > 1], "the same failure twice"


def test_the_rows_with_nothing_are_counted_and_say_so():
    assert not [row[0] for row in ROWS if not row[3].strip() or not row[4].strip()], "write `none` rather than leaving a column blank"
    no_prevent = sum(1 for row in ROWS if row[3] == "none")
    no_fix = sum(1 for row in ROWS if row[4] == "none")
    neither = sum(1 for row in ROWS if not tokens_of(row))
    assert f"{no_prevent} rows have nothing listed to prevent them, {no_fix} have nothing listed to find or fix them, and {neither} {'has' if neither == 1 else 'have'} neither." in DOCUMENT


def test_every_scan_rule_named_is_a_real_rule():
    named = {token[5:] for row in ROWS for token in tokens_of(row) if token.startswith("scan:")}
    assert named and not named - set(BY_ID)


def test_every_query_and_tool_named_is_a_real_command():
    tokens = {token for row in ROWS for token in tokens_of(row)}
    assert {token[6:] for token in tokens if token.startswith("query:")} <= commands("query")
    assert {token[5:] for token in tokens if token.startswith("tool:")} <= commands()


def test_every_other_token_is_listed_with_where_it_lives():
    tokens = {token for row in ROWS for token in tokens_of(row) if token.startswith(("hook:", "note:", "gate:", "guide:"))}
    assert not tokens - set(MECHANISMS)


@pytest.mark.parametrize("token", sorted(MECHANISMS))
def test_each_mechanism_is_where_this_says(token):
    path, proof = MECHANISMS[token]
    assert proof in (ROOT / path).read_text(), f"{token}: {proof!r} is gone from {path}. Update the catalog, since what it claims may no longer hold."


def test_the_counts_at_the_top_match_the_rows():
    counts = Counter(level_of(tokens_of(row)) for row in ROWS)
    for level, name in LEVEL_NAMES.items():
        assert re.search(rf"^\| {re.escape(name)} \| {counts[level]} \|", DOCUMENT, re.M), f"{name} should say {counts[level]}"
    assert f"| **Total** | **{len(ROWS)}** |" in DOCUMENT


def test_each_area_row_adds_up():
    areas = re.findall(r"^\| \[[^\]]+\]\(#([a-z]+)-[^)]*\) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", DOCUMENT, re.M)
    assert areas
    for code, total, *levels in areas:
        rows = [row for row in ROWS if row[0].lower().startswith(code + "-")]
        assert len(rows) == int(total) == sum(int(level) for level in levels), code


def test_every_source_cited_is_listed():
    listed = {int(number) for number in re.findall(r"^\| (\d+) \| \[", DOCUMENT, re.M)}
    cited = {int(number) for row in ROWS for number in re.findall(r"\[(\d+)\]", row[2])}
    assert cited and not cited - listed
    assert not [row[0] for row in ROWS if not re.match(r"(\[\d+\]|own)", row[2])], "a row with no source and not marked as our own"


def test_every_new_check_is_used_by_some_row():
    tokens = {token for row in ROWS for token in tokens_of(row)}
    from occam_tools import change_checks  # noqa: PLC0415

    source = Path(change_checks.__file__).read_text()
    rules = set(re.findall(r'_note\("([a-z-]+)"', source))
    assert rules and not {f"gate:{rule}" for rule in rules if rule != "crosses-owners"} - tokens
