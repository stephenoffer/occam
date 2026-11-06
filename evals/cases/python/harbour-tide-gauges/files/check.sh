#!/usr/bin/env bash
# What CI runs on every push.
set -euo pipefail
python3 -m ruff check .
python3 -m pytest -q
python3 -m pytest -q --doctest-modules tidekit
