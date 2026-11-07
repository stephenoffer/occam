"""What the design doc's tests share: a document, a repository holding it, and an agent editing there. A pytest plugin, so its fixtures need no import."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import design  # noqa: E402, F401
from test_occam_hook import Agent  # noqa: E402
from test_tools import Repo  # noqa: E402


def design_tool():
    return ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"


DOC = """# Design: shop

Owner: Sam. Verified 2026-01-01 against 0000000.

Where this file and the code disagree about what exists, the code is right.

## Problem

Shops lose orders.

## Non-goals

- Multi-currency.

## Current design

- Billing lives in `app/billing.py`.
- Routes live in `app/web/`.

## Planned

- A queue in `app/queue.py`.

## Contracts

- `app/billing.py` returns cents as an integer.

## Decisions

- 2026-01-01 use-cents [accepted] Money is integer cents. Why: floats lost pennies. Applies: `app/billing.py`.
- 2026-01-02 old-idea [accepted] Retry three times. Why: guess. Applies: `app/retry.py`.
- 2026-01-03 new-idea [accepted] Retry once. Why: measured. Applies: `app/retry.py`. Supersedes: `old-idea`.
- 2026-01-04 maybe-queue [proposed] Add a queue. Why: spikes. Applies: `app/billing.py`.
"""


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    made = Repo(path, tmp_path / "state")
    made.git("init", "-q", "-b", "main")
    made.write("app/billing.py", "def charge(cents):\n    return cents\n\n\nprint(charge(1))\n")
    made.write("app/web/routes.py", "print(1)\n")
    made.write("app/retry.py", "print(2)\n")
    made.write("other.py", "print(3)\n")
    made.write("DESIGN.md", DOC)
    made.commit()
    return made


def _decide(args):
    root, index = args
    return design.decide(Path(root), f"parallel-{index}", f"Decision {index}", "racing", [], False, None)[1]


def _history(repo, together):
    for index in range(together):
        repo.write("app/rates.py", f"RATE = {index}\n")
        repo.write("app/rates_table.py", f"TABLE = {index}\n")
        repo.commit()


def additional(result):
    return (result or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


@pytest.fixture
def agent(tmp_path):
    made = Agent(tmp_path)
    made.prompt("change the billing helper")
    made.load()
    return made


def _write(agent, name, content):
    path = Path(agent.path(name))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _decision_ids(text):
    return [decision.id for decision in design.in_force(design.parse(text))]


def _verified(repo, text=DOC):
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.write("DESIGN.md", text.replace("against 0000000", f"against {head}"))
    repo.commit()
    return head


def _git_agent(agent):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=agent.project, check=True, capture_output=True)


HAND_WRITTEN = """# Payments design

**Owner:** Sam Reyes
Verified 2026-01-01 against {commit}.

## Problem

Payments are slow.

## Non-Goals

- Rewrite in `rust/lib.rs`.

## Current Design

- The handler is `app/billing.py`. It uses Go's `net/http.Client` and `encoding/json.Marshal`.
- YAML: `gopkg.in/yaml.v3`. Deploys `origin/release-1.2`. Python `python/3.9`. Media type `application/vnd.api+json`.
- Secrets in `~/.ssh/id_rsa.pub`, config `~/.config/pay.json`. Image `ghcr.io/acme/pay.v2`. Module `@acme/pay.js`.

## Alternatives Considered

- We rejected `queue/kafka.py` because of cost.

## Future Work

- Add `app/refunds/core.py`.

## Decisions

- 2026-01-01 use-cents [accepted] Keep money in cents. Why: `old/floats.py` lost a cent. Applies: `app/billing.py`.
"""


def _hand_written(repo):
    repo.write("DESIGN.md", HAND_WRITTEN.format(commit=repo.git("rev-parse", "--short", "HEAD").strip()))
    return repo.occam("design", "check").stdout


STOCK_PYTHON = Path("/usr/bin/python3")


stock_only = pytest.mark.skipif(not STOCK_PYTHON.exists(), reason="no stock python here")


def _stock(repo, *args):
    return subprocess.run([str(STOCK_PYTHON), str(design_tool()), *args], cwd=repo.path, env=repo.env, capture_output=True, text=True)
