#!/usr/bin/env bash
# What CI runs on every push.
set -euo pipefail
ruff check .
ruff format --check .
mypy
python3 -m pytest
