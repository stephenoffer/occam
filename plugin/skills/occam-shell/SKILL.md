---
name: occam-shell
description: Shell guidance on quoting, arrays, failure handling gaps, GNU and BSD portability, temp files, untrusted input. Use alongside occam to write, debug or review shell scripts.
---

# Shell

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Quoting:** quote expansions (`"$var"`), including in loops. Use arrays for argument lists. Don't build commands with `eval`, and parse `find` output with `-print0`, not `ls`.
- **Failure:** `set -euo pipefail` helps but has gaps: it doesn't apply in some conditionals, and command substitution inside `local` hides failures. Check what must succeed.
- **Portability:** check the shebang and targets. `sed -i`, `date`, `readlink` and `grep -P` differ between GNU and BSD, and bash features aren't in POSIX `sh`.
- **Temp files and input:** use `mktemp` with a `trap` for cleanup. Treat filenames and environment values as untrusted, and use `--` to end options before user-supplied paths.
- **Scope:** past about a hundred lines, or once real data structures appear, consider whether a script in a proper language would cost less to maintain.
- **What generated code gets wrong here:** no strict mode, unquoted variables in `rm`, `|| true` hiding failures, `curl | sh`, `ls` parsing, GNU-only flags on macOS, and scripts grown past what shell handles well. `shellcheck` comes first, and it finds more than `occam-audit`'s scanner does here. Without it, `occam scan` reads each script with `bash -n` and looks for these.
