"""Patterns AI-written code produces often, which the scanner and `gate` missed when run on a small app written to contain them, on 2026-11-06.

Each has a case that must be found and a near miss that must not, the way `test_scanner_rules.py` does. Precision comes first: the near misses
are the ordinary code each change could have started reporting, and several come from what the scanner reported on a large real repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from query_support import python_repo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import scan  # noqa: E402


def rules_in(findings) -> set[str]:
    return {f["rule"] for f in findings}


def scan_files(folder: Path, files: dict) -> list[dict]:
    for name, content in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(content)
    return scan.run_scan(folder, use_cache=False).findings


ONE_FILE = [
    # The same success value from the work and from a broad handler, so the caller can't tell them apart
    ("failure-reported-as-success", "app/db.py",
     "def save(order):\n    try:\n        db.insert(order)\n        db.commit()\n        return True\n    except Exception as e:\n        print(e)\n        return True\n",
     "def save(order):\n    try:\n        db.insert(order)\n        return True\n    except Exception as e:\n        log.error(e)\n        return False\n"),
    ("failure-reported-as-success", "app/files.py",
     "def store(path):\n    try:\n        write(path)\n    except BaseException:\n        return 'ok'\n    return 'ok'\n",
     "import os\ndef remove(path):\n    try:\n        os.remove(path)\n        return True\n    except FileNotFoundError:\n        return True\n"),  # already gone is deleted
    # A test calling the mock `@patch` handed it
    ("test-mocks-subject", "tests/test_pay.py",
     "from unittest.mock import patch\n@patch('app.payments.charge_card')\ndef test_charge(mock_charge):\n    mock_charge.return_value = {'status': 'ok'}\n    assert mock_charge(1, 2)['status'] == 'ok'\n",
     "from unittest.mock import patch\nfrom app.payments import charge_card\n@patch('app.payments.gateway')\ndef test_charge(mock_gateway):\n    mock_gateway.return_value = 1\n    assert charge_card(1, 2) == 1\n"),
    ("test-mocks-subject", "tests/test_jobs.py",
     "from unittest.mock import patch\n@patch('app.jobs.notify')\n@patch('app.jobs.fetch')\ndef test_job(mock_fetch, mock_notify):\n    assert mock_fetch(3) is not None\n",
     "from unittest.mock import patch\nfrom app.jobs import run_job\n@patch('app.jobs.notify')\ndef test_job(mock_notify):\n    run_job(on_done=mock_notify)\n    mock_notify()\n    mock_notify.assert_called()\n"),  # hands it to real code
    # Row by row through a frame, at module level as notebook cells and scripts are written
    ("dataframe-iterrows", "analysis.py",
     "import pandas as pd\ndf = pd.read_csv('sales.csv')\nfor i in range(len(df)):\n    row = df.iloc[i]\n    print(row['price'])\n",
     "import pandas as pd\ndf = pd.read_csv('sales.csv')\nfor i in range(len(df)):\n    print(i)\n"),
    # Tests that check through what they say or what they call
    ("test-no-assert", "tests/test_resize.py", "def test_resize():\n    resize(3)\n",
     "def test_resize_same_size():\n    # Should not raise: the size is unchanged.\n    resize(3)\n"),
    ("test-no-assert", "tests/test_launch.py", "def test_launch():\n    launch(make())\n",
     "from smoke_tests import smoke_tests_utils\ndef test_launch():\n    smoke_tests_utils.run_one_test(make())\n"),
]


@pytest.mark.parametrize("rule, path, positive, negative", ONE_FILE, ids=[f"{c[0]}-{i}" for i, c in enumerate(ONE_FILE)])
def test_one_file(rule, path, positive, negative):
    assert rule in rules_in(scan.scan_text(path, positive)), f"{rule} should fire"
    assert rule not in rules_in(scan.scan_text(path, negative)), f"{rule} shouldn't fire on the near miss"


_FORMAT = "def {name}({arg}):\n    if {arg} is None:\n        return '{zero}'\n    return '${{:,.2f}}'.format(float({arg}))\n"
_LOOKUP = "def get_user(conn, name):\n    return conn.execute('SELECT * FROM users WHERE name = ?', (name,)).fetchone()\n"

PROJECT = [
    # N+1 through a helper in another file
    ("query-in-loop",
     {"app/db.py": _LOOKUP, "app/views.py": "from app.db import get_user\ndef users(conn, names):\n    return [get_user(conn, n) for n in names]\n"},
     {"app/db.py": "import functools\n@functools.lru_cache\n" + _LOOKUP, "app/views.py": "from app.db import get_user\ndef users(conn, names):\n    return [get_user(conn, n) for n in names]\n"}),
    ("query-in-loop",
     {"app/views.py": _LOOKUP + "def users(conn, names):\n    out = []\n    for n in names:\n        out.append(get_user(conn, n))\n    return out\n"},
     {"app/views.py": "def label(name):\n    return name.title()\ndef users(names):\n    return [label(n) for n in names]\n"}),
    # Three copies of a short function, which structure alone can't tell from unrelated code
    ("clone-function",
     {"app/a.py": _FORMAT.format(name="format_currency", arg="amount", zero="$0.00"), "app/b.py": _FORMAT.format(name="format_money", arg="value", zero="$0.00"),
      "app/c.py": _FORMAT.format(name="format_price", arg="amount", zero="$0.00")},
     {"app/a.py": _FORMAT.format(name="format_currency", arg="amount", zero="$0.00"), "app/b.py": _FORMAT.format(name="format_money", arg="value", zero="$0.00"),
      "app/c.py": _FORMAT.format(name="format_price", arg="amount", zero="-")}),
    # A famous package isn't invented, only undeclared. Packages chosen because they're rarely installed, so the test reaches that branch
    ("undeclared-dependency",
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = []\n', "app/a.py": "import lightgbm\nprint(lightgbm)\n"},
     {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["lightgbm"]\n', "app/a.py": "import lightgbm\nprint(lightgbm)\n"}),
    # setup.py that builds install_requires from a module beside it
    ("phantom-import",
     {"pkg/setup.py": "import runpy\ndeps = runpy.run_path('dependencies.py')\nsetup(install_requires=deps['install_requires'])\n",
      "pkg/dependencies.py": "install_requires = [\n    # don't pin this one\n    'flask_login>=1',\n]\n", "app/a.py": "import flask_superauth\nprint(flask_superauth)\n"},
     {"pkg/setup.py": "import runpy\ndeps = runpy.run_path('dependencies.py')\nsetup(install_requires=deps['install_requires'])\n",
      "pkg/dependencies.py": "install_requires = [\n    # don't pin this one\n    'flask_superauth>=1',\n]\n", "app/a.py": "import flask_superauth\nprint(flask_superauth)\n"}),
]


@pytest.mark.parametrize("rule, positive, negative", PROJECT, ids=[f"{c[0]}-{i}" for i, c in enumerate(PROJECT)])
def test_project(rule, positive, negative, tmp_path):
    (tmp_path / "yes").mkdir()
    (tmp_path / "no").mkdir()
    assert rule in rules_in(scan_files(tmp_path / "yes", positive)), f"{rule} should fire"
    assert rule not in rules_in(scan_files(tmp_path / "no", negative)), f"{rule} shouldn't fire on the near miss"


def test_a_cell_importing_famous_packages_has_no_invented_ones(tmp_path):
    findings = scan_files(tmp_path, {"cell.py": "import streamlit as st\nimport gradio as gr\nimport pandaz_toolkit\nprint(st, gr, pandaz_toolkit)\n"})
    phantoms = [f["message"] for f in findings if f["rule"] == "phantom-import"]
    assert len(phantoms) == 1 and "pandaz_toolkit" in phantoms[0]
    assert "undeclared-dependency" not in rules_in(findings)  # nothing is declared anywhere, so there's nothing to fall short of


def test_the_rule_reading_a_helper_sees_through_one_hop_only(tmp_path):
    """A loop calling a helper that calls a helper that queries isn't reported: one hop keeps it to what the reader can check at a glance."""
    files = {"app/db.py": _LOOKUP + "def user_label(conn, name):\n    return get_user(conn, name)[0]\n",
             "app/views.py": "from app.db import user_label\ndef labels(conn, names):\n    return [user_label(conn, n) for n in names]\n"}
    assert not [f for f in scan_files(tmp_path, files) if f["rule"] == "query-in-loop" and f["path"] == "app/views.py"]


def test_gate_names_options_nothing_reads_and_comments_that_narrate(tmp_path):
    repo = python_repo(tmp_path, {"app/money.py": "def get_total(items):\n    return sum(items)\n"})
    repo.write("app/money.py", "def get_total(items):\n    return sum(items)\n\n\n"
               "def format_total(items, currency='$', use_cache=False, retries=3, _hint=None):\n"
               "    # Get the total of the items\n    total = get_total(items)\n    return f'{currency}{total:.2f}'\n\n\n"
               "def handler(event, context):\n    raise NotImplementedError\n")
    done = repo.occam("gate")
    assert "never reads use_cache, retries." in done.stdout
    assert "_hint" not in done.stdout and "handler never reads" not in done.stdout  # a stub reads nothing by design
    assert "narration-comment" in done.stdout
    assert "occam query impact --changed" in done.stdout  # which existing tests to rerun, asked where the work gets reviewed
    assert not [line for line in done.stdout.splitlines() if line.lstrip().startswith("!") and ("unread-parameter" in line or "narration" in line)]  # warnings only


def test_a_handler_that_says_why_it_reports_success_is_a_low_confidence_lead():
    code = ("def reachable(context):\n    try:\n        probe(context)\n        return True\n    except Exception:\n"
            "        # Reachable but restricted, so we don't wrongly skip a live cluster.\n        return True\n")
    found = [f for f in scan.scan_text("app/debug.py", code) if f["rule"] == "failure-reported-as-success"]
    assert [f["confidence"] for f in found] == ["low"]
    silenced = code.replace("# Reachable but restricted, so we don't wrongly skip a live cluster.", "# pylint: disable=broad-except")
    assert [f["confidence"] for f in scan.scan_text("app/debug.py", silenced) if f["rule"] == "failure-reported-as-success"] == ["medium"]


def test_the_names_of_extras_are_not_packages(tmp_path):
    files = {"pkg/setup.py": "import runpy\ndeps = runpy.run_path('dependencies.py')\nsetup(install_requires=deps['install_requires'], extras_require=deps['extras'])\n",
             "pkg/dependencies.py": "install_requires = ['flask_superauth>=1']\nextras = {'aws': ['flask_superauth'], 'do': []}\n",
             "app/a.py": "import flask_superauth\nprint(flask_superauth)\n"}
    findings = scan_files(tmp_path, files)
    assert not [f for f in findings if f["rule"] == "unused-dependency" and ("'aws'" in f["message"] or "'do'" in f["message"])]
    assert "phantom-import" not in rules_in(findings)
