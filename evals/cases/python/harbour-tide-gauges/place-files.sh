#!/usr/bin/env bash
set -eu
here="$(dirname "$0")"
cp -R "$here/files/." .
chmod +x check.sh
commit() {
  GIT_AUTHOR_DATE="$2" GIT_COMMITTER_DATE="$2" git -c user.name="$3" -c user.email="$4" commit -qm "$1"
}
# The repository as it was before Friday's merge.
cp -R "$here/before-merge/." .
git init -q .
git add -A
commit "Initial import" "2026-10-12T10:00:00-03:00" maintainer maintainer@example.invalid
# Friday's merge.
cp "$here/files/tidekit/datum.py" tidekit/datum.py
git add -A
commit "Merge corrector tidy-up (#212)" "2026-10-30T16:40:00-03:00" "Priya Raman" priya.raman@harbour.invalid
