---
description: Cut what the current change doesn't need, without changing what it does. Give a path to work on that instead.
argument-hint: "[path]"
disable-model-invocation: true
---

Load the `occam` skill if it isn't loaded, then apply the razor to $ARGUMENTS, or to the uncommitted change when that's empty, or to the last commit when the tree is clean.

For each thing the code adds, ask whether the requirement needs it to exist: a layer or interface with one implementation, an option nothing passes, a wrapper that only forwards, a helper the standard library or this repository already has, a second copy of existing logic, dead code, a comment that repeats the code. The occam tools find leads with `scan --changed` and `gate`, or `scan <path>`, or for the last commit `scan --diff HEAD~1` and `gate --base HEAD~1`. Confirm each lead by reading before acting on it.

Cut only what a check shows changes no behavior: the relevant tests run before and after, or `golden` where nothing tests it. Validation, error handling, security checks and tests aren't bloat, so they stay. Nothing beyond what the requirement needs, and nothing less. Leave code outside the scope alone, and if the request only asks what could go, list the cuts instead of making them.

Report the lines before and after, each cut and why, and anything that looked cuttable but stayed, with the reason.
