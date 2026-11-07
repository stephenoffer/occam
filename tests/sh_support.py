"""What the `occam.sh` tests share: a small real repository and the commands to run on it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugin" / "skills" / "occam" / "scripts"
TOOL = SCRIPTS / "occam.sh"
OCCAM = SCRIPTS / "occam.py"
GIT = shutil.which("git")
TOKEN = "ghp_" + "a1B2" * 10
sys.path.insert(0, str(SCRIPTS))
BASHES = sorted({found for found in (shutil.which("bash"), "/bin/bash" if os.path.exists("/bin/bash") else None) if found})
SOURCE = TOOL.read_text()

FILES = {
    ".gitignore": "__pycache__/\nignored.py\n",
    ".occam.json": '{\n  "ignore": ["fixtures", "*.skipme.py"]\n}\n',
    "pyproject.toml": '[project]\nname = "demo"\n\n[tool.pytest.ini_options]\n\n[tool.ruff]\nline-length = 100\n',
    "Makefile": "build:\n\tpython -m build\n\ntest:\n\tpytest -q\n\n.PHONY: build\n",
    "package.json": '{\n  "name": "x",\n  "scripts": {\n    "lint": "eslint ."\n  }\n}\n',
    "Dockerfile": 'FROM python:3\nCMD ["python", "tool.py"]\n',
    ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - run: ruff check .\n      - run: |\n          pytest -q\n          echo done\n",
    "README.md": "total appears here\n",
    "app/core.py": 'def total(a):\n    return a\n\n\nif __name__ == "__main__":\n    print(total(1))\n',
    "app/api.py": 'from app.core import total\n\n\n@app.get("/health")\ndef health():\n    return total(1)  # noqa: E501\n',
    "app/no_newline.py": "x = 1",
    "app/spaced name.py": "y = 2\ntotal = 3\n",
    "app/-dash.py": "z = 3\n",
    "app/ünicode.py": "total = 4\n",
    "tests/test_core.py": "from app.core import total\n\n\ndef test_total():\n    assert total(1) == 1\n",
    "tests/test_skip.py": "import pytest\n\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n",
    "web/app.test.js": "it.only('x', () => {})\n",
    "fixtures/skipped.py": "total = 5\n",
    "a.skipme.py": "total = 6\n",
    "vendor/lib.py": "total = 7\n",
    "dist/out.min.js": "total = 8\n",
    "go.sum": "x\n",
    "bin/run": "#!/usr/bin/env bash\nset -e\necho hi\n",
    "bin/data": "not a script\n",
    "scripts/deploy.sh": '#!/bin/sh\nrm -rf "$dir"/*\nfor f in $(ls); do echo "$f"; done\n',
}


class Repo:
    def __init__(self, path: Path, state: Path, bash: str) -> None:
        self.path, self.bash = path, bash
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

    def sh(self, *args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([self.bash, str(TOOL), *args], cwd=cwd or self.path, env=env or self.env, capture_output=True, text=True, timeout=120)

    def py(self, *args: str) -> dict:
        done = subprocess.run([sys.executable, str(OCCAM), "query", *args, "--format", "json"], cwd=self.path, env=self.env, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)


def make_repo(path: Path, state: Path, bash: str, git: bool = True) -> Repo:
    path.mkdir()
    repo = Repo(path, state, bash)
    for name, content in FILES.items():
        repo.write(name, content)
    if git:
        repo.git("init", "-q")
        repo.commit("init")
    return repo
