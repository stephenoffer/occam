#!/usr/bin/env bash
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
cp -R "$here/files/." .
python3 -B "$here/generate_tree.py" .
git init -q .
git -c user.name=maintainer -c user.email=maintainer@example.invalid add -A
git -c user.name=maintainer -c user.email=maintainer@example.invalid commit -qm "Initial import"
