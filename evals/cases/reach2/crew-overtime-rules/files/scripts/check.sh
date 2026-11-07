#!/usr/bin/env bash
# Tests plus a byte-compile of every module. Run from the repository root.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q common timesheets payroll costing ledger rostering exports
python3 -m pytest -q
