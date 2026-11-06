#!/usr/bin/env bash
set -eu
here="$(dirname "$0")"
cp -R "$here/files/." .
git init -q .
git -c user.name=maintainer -c user.email=maintainer@example.invalid add -A
git -c user.name=maintainer -c user.email=maintainer@example.invalid commit -qm "Initial import"
# Another developer's uncommitted work in progress, overlapping the file being fixed.
cp -R "$here/wip/." .
