---
description: Review the current change without editing anything. What's wrong, what's missing, and what it didn't need.
argument-hint: "[path or revision]"
disable-model-invocation: true
---

This is review-only, so make no edits. Load the `occam` skill if it isn't loaded, then review $ARGUMENTS, or the uncommitted change when that's empty, or the last commit when the tree is clean.

Work out what the change was meant to do, then read the diff against it as someone who expects it to be wrong. Run the occam tools' `gate` and `scan --changed` (for a commit, `gate --base REV` and `scan --diff REV`), and the project's own tests and linters where they're quick. Look for inputs and states that break it, callers it left behind, tests that can't fail, code it didn't need, and anything it claims that it doesn't do.

Open with a sentence or two on whether the change is ready and what matters most. Then the findings, ranked by what to fix first, each in plain words with its location, the input or state that triggers it, and your evidence. Label each one confirmed or a lead, and say what you didn't check.
