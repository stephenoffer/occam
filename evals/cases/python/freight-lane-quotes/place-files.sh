#!/usr/bin/env bash
set -eu
cp -R "$(dirname "$0")/files/." .
chmod +x scripts/check.sh
git init -q .
git -c user.name=maintainer -c user.email=maintainer@example.invalid add -A
git -c user.name=maintainer -c user.email=maintainer@example.invalid commit -qm "Initial import"
