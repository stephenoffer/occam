"""What the `occam query` tests share: a small real repository and the commands to run on it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugin" / "skills" / "occam" / "scripts"
OCCAM = SCRIPTS / "occam.py"
GIT = shutil.which("git")
TOKEN = "ghp_" + "a1B2" * 10
sys.path.insert(0, str(SCRIPTS))

CORE = '''"""Core."""
import os


def total(a, b=1, *, cap=None):
    """Add."""
    if a > 0 and b > 0:
        return a + b
    return 0


class Ledger:
    def post(self, amount):
        return total(amount)

    def _hidden(self):
        return 1


def _private():
    return os.environ["A"]


if __name__ == "__main__":
    print(total(1))
'''
API = '''from app.core import total

try:
    from app import optional_part
except ImportError:
    optional_part = None


def load():
    from app import lazy_part
    return lazy_part.value() + total(2)


# total is mentioned in this comment
LABEL = "total"
TARGET = "app.core.total"
'''
FILES = {
    ".gitignore": "__pycache__/\n",
    "pyproject.toml": '[project]\nname = "demo"\n\n[project.scripts]\ndemo = "app.api:load"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n[tool.ruff]\nline-length = 100\n',
    "README.md": "# Demo\n\n```console\n$ pytest -q\n3 passed\n$ make build\n```\n\nThe word total appears here.\n",
    "Makefile": "build:\n\tpython -m build\n\ntest:\n\tpytest -q\n\n.PHONY: build\n",
    "Dockerfile": 'FROM python:3.12\nCMD ["python", "tool.py"]\n',
    ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - run: ruff check .\n      - run: |\n          pytest -q\n          echo done\n",
    "app/__init__.py": "",
    "app/core.py": CORE,
    "app/api.py": API,
    "app/optional_part.py": "VALUE = 1\n",
    "app/lazy_part.py": "def value():\n    return 1\n",
    "app/lonely.py": "".join(f"def f{i}():\n    return {i}\n" for i in range(20)),
    "app/payments.py": 'import subprocess\nimport requests\n\n\ndef charge(amount, tenant_id):\n    db.execute("SELECT 1")\n    subprocess.run(["ls"])\n    return requests.post("https://x.invalid", timeout=1)\n\n\n# price is only mentioned here: stripe\n',
    "web/server.py": '@app.get("/health")\ndef health():\n    return 1\n\n\n# @app.post("/commented/out")\n',
    "tool.py": 'from app.api import load\n\nif __name__ == "__main__":\n    load()\n',
    "tests/__init__.py": "",
    "tests/test_core.py": "from app.core import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n",
    "tests/test_tool.py": 'import subprocess\n\n\ndef test_tool():\n    subprocess.run(["python", "tool.py"], check=True)\n',
    "tests/test_lazy_part.py": "def test_named_after_it():\n    assert True\n",
    "vendor/pkg/lib.py": "def total():\n    return 99\n",
    "dist/out.min.js": "function total(){}\n",
    "scripts/run.sh": '#!/bin/bash\nset -e\nsource ./lib.sh\necho hi\n',
    "scripts/lib.sh": "greet() {\n  echo hi\n}\n",
    "bin/noext": "#!/usr/bin/env python3\nprint(1)\n",
}


class Repo:
    def __init__(self, path: Path, state: Path) -> None:
        self.path = path
        self.env = {**os.environ, "OCCAM_STATE_DIR": str(state), "GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "a@example.invalid",
                    "GIT_COMMITTER_NAME": "Ann", "GIT_COMMITTER_EMAIL": "a@example.invalid", "PYTHONDONTWRITEBYTECODE": "1"}

    def write(self, name: str, content: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def git(self, *args: str, author: str = "Ann") -> str:
        return subprocess.run([GIT, *args], cwd=self.path, env={**self.env, "GIT_AUTHOR_NAME": author}, capture_output=True, text=True, check=True).stdout

    def commit(self, message: str = "c", author: str = "Ann") -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message, author=author)

    def occam(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(OCCAM), *args], cwd=cwd or self.path, env=self.env, capture_output=True, text=True, timeout=120)

    def query(self, *args: str, cwd: Path | None = None) -> dict:
        done = self.occam("query", *args, "--format", "json", cwd=cwd)
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)

    def text(self, *args: str) -> str:
        done = self.occam("query", *args)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout


def make_repo(path: Path, state: Path, git: bool = True) -> Repo:
    path.mkdir()
    repo = Repo(path, state)
    for name, content in FILES.items():
        repo.write(name, content)
    if git:
        repo.git("init", "-q")
        repo.commit("init")
    return repo


def python_repo(tmp_path, files: dict) -> Repo:
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    for name, content in files.items():
        repo.write(name, content)
    repo.git("init", "-q")
    repo.commit()
    return repo
