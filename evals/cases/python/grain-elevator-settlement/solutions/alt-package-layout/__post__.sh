#!/usr/bin/env bash
set -eu
REF="$(dirname "$0")/../reference/grainbank"
mkdir grainbank/settlement_new
cp "$REF"/*.py grainbank/settlement_new/
mv grainbank/settlement_new/settlement.py grainbank/settlement_new/__init__.py
rm grainbank/settlement.py
mv grainbank/settlement_new grainbank/settlement
sed -i '' 's/^from \.taskapp import/from ..taskapp import/' grainbank/settlement/__init__.py grainbank/settlement/jobs.py
