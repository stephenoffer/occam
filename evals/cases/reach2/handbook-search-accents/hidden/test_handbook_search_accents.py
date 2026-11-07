"""Accent-insensitive search, checked the way the team runs findoc.

Every check copies the sample handbook as it was before the task (kept in
hidden/starter/handbook, so edits to the workspace's pages can't change the
question) and runs the finished code's CLI in a fresh process.

The upgrade check reproduces a teammate's checkout: the old code's post-merge
hook built an index, then they pull the change, the hook runs the new code's
`findoc reindex`, and they search.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

STARTER = Path(__file__).parent / "starter"
CAFE_PAGE = "office/cafe-opening-hours.md"
PLAIN_CAFE_PAGE = "people/coffee-and-snacks.md"
ZURICH_PAGE = "office/zurich.md"
EXPECTED = {
    "cafe": {CAFE_PAGE, PLAIN_CAFE_PAGE},
    "café": {CAFE_PAGE, PLAIN_CAFE_PAGE},
    "Cafe": {CAFE_PAGE, PLAIN_CAFE_PAGE},
    "zurich": {ZURICH_PAGE},
    "Zürich": {ZURICH_PAGE},
}


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout" / "handbook"
    shutil.copytree(STARTER / "handbook", root)
    return root


def run_new(py, *args):
    done = py("-m", "findoc", *args)
    assert done.returncode == 0, f"findoc {' '.join(args)} failed:\n{done.stderr[-2000:]}"
    return done.stdout


def run_old(tmp_path, *args):
    env = {**os.environ, "PYTHONPATH": str(STARTER), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-m", "findoc", *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout


def results(py, root, query):
    out = json.loads(run_new(py, "search", str(root), query, "--json", "--limit", "50"))
    return {result["path"]: result for result in out["results"]}


def missing_pages(py, root):
    missing = {}
    for query, expected in EXPECTED.items():
        absent = expected - set(results(py, root, query))
        if absent:
            missing[query] = sorted(absent)
    return missing


def test_search_ignores_accents_on_a_fresh_checkout(py, checkout):
    missing = missing_pages(py, checkout)
    assert not missing, f"pages not found, by query: {missing}"


def test_search_ignores_accents_after_upgrading_a_checkout(py, checkout, tmp_path):
    run_old(tmp_path, "reindex", str(checkout), "--quiet")
    assert (checkout / ".findoc" / "index.json").exists(), "the old code didn't build an index"
    run_new(py, "reindex", str(checkout), "--quiet")
    missing = missing_pages(py, checkout)
    assert not missing, f"after upgrading a checkout that already had an index, pages not found, by query: {missing}"


def test_snippets_highlight_accent_insensitive_matches(py, checkout):
    accented = results(py, checkout, "cafe").get(CAFE_PAGE)
    assert accented is not None, "searching cafe doesn't find the Café page at all"
    assert "**Café**" in accented["snippet"], accented["snippet"]
    plain = results(py, checkout, "café").get(PLAIN_CAFE_PAGE)
    assert plain is not None, "searching café doesn't find the page that says cafe"
    assert "**cafe**" in plain["snippet"], plain["snippet"]
    zurich = results(py, checkout, "zurich").get(ZURICH_PAGE)
    assert zurich is not None, "searching zurich doesn't find the Zürich page"
    assert "**Zürich**" in zurich["snippet"], zurich["snippet"]
