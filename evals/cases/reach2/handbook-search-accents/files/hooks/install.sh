#!/bin/sh
# Install findoc's git hooks into this clone and build the first index.
set -eu
top=$(git rev-parse --show-toplevel)
hooks_dir=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_dir"
cp "$top/hooks/post-merge" "$hooks_dir/post-merge"
chmod +x "$hooks_dir/post-merge"
echo "installed post-merge hook in $hooks_dir"
cd "$top"
python3 -m findoc reindex handbook
