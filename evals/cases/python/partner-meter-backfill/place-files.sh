#!/usr/bin/env bash
set -eu
here="$(dirname "$0")"
cp -R "$here/files/." .
chmod +x tools/push-rollups
mkdir -p samples
base64 --decode < "$here/samples-b64/acme-2026-01.npz.b64" > samples/acme-2026-01.npz
git init -q .
git add -A . ':!pyproject.toml' ':!requirements.lock'
git -c user.name=maintainer -c user.email=maintainer@example.invalid commit -qm "Initial import"
git add -A .
git -c user.name=maintainer -c user.email=maintainer@example.invalid commit -qm "Pin click, numpy and pandas to current releases"
