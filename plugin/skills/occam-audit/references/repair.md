# Repair

## Ask first, once, with something concrete

After the report, if there is anything beyond tier A and B inside an authorized fix, ask. Bundle related decisions, ask at most four things at a time, use the host's question tool if it has one, and always give your recommendation. `occam ledger decisions` collects what's waiting.

> `api/orders.py:41` returns every order in the table, with no paging, and `web/list.js` is its only caller. **Proposed:** add `limit` and `cursor`, default 50, and update the caller, which is ready on this branch. **Alternative:** keep the response shape and cap it silently at 1,000, which breaks anyone relying on the full list. **I recommend** paging. Apply it?

Scoping questions worth asking before a large repair, if the request doesn't answer them: which tiers, which directories, whether to commit per batch or leave changes uncommitted, and what must not change.

Don't ask about routine repairs that are already authorized, and don't ask "may I continue?". If nobody can answer, do the authorized part and report the decision still needed. "It touches money" or "it affects behavior" isn't a decision when the documentation already states the rule, or when a guarded update closes a double charge without a schema change.

## Lock behavior before you change it

Most AI-generated code has weak tests, so passing tests prove little. Before a tier B or C repair:

- **Add a characterization test** for what the code does now, through its public entry point, including the odd cases. If it pins a bug you're about to fix, note that.
- **Or record it:** `occam golden record NAME -- <command>`, then `occam golden check NAME` after the change. It refuses nondeterministic commands until you blank what varies with `--normalize`.
- **Check the tests can fail:** `occam mutate --cmd "<test command>" <path>` breaks a temporary copy and reports what nothing notices. Add tests only for survivors that matter.

## Order of work

Each step makes the next one safer or smaller:

1. **Security and data loss.** Anything exploitable or lossy comes first, in its own batch.
2. **Unfinished paths.** Decide with the user: finish it, remove it, or fail clearly. A stub that fails loudly beats one that pretends.
3. **Unmasked errors.** Fix swallowed exceptions before anything else in that code, because they hide what your later checks would show. Expect new failures to surface. That is the repair working.
4. **Real tests** around what remains risky.
5. **Delete** dead code, orphans and residue. Do this before refactoring, so you don't refactor what you're about to delete.
6. **Consolidate** duplication. Near-copies may have drifted: `diverged-twin` means they disagree, so decide which behavior is right before merging, and treat the disagreement as a possible bug.
7. **Simplify structure.** Remove layers that only forward, then split what's too large along seams that already exist.
8. **Scale and performance,** against the stated workload, with `occam bench`. Fix the whole path, then re-measure.
9. **Names and comments last,** since they churn every line they touch and make other diffs unreadable. Public names need a deprecation path, which makes them tier C.

Don't mix these in one batch. A diff that moves code and changes behavior can't be reviewed.

## Cleaning up slop

Cleanup is where a well-meant agent does the most quiet damage, and readability work by agents often makes maintainability numbers worse. These hold on top of the tiers.

- **Keep to what was asked.** For one branch, read the diff against its base with `occam gate --base` and `occam scan --diff`. A request about a branch isn't a license to clean the repository.
- **Measure what you claim to improve.** Note scan counts and `occam gate`'s size line before and after, and if a cleanup adds lines or complexity, say why. Renames and reformatting rarely improve much, so don't lead with them.
- **Judge excess against the file, not a rule.** Comments, handlers and casts are slop when they're out of line with the code around them. Match that norm.
- **A text match proves nothing yet.** Before deleting, check tests, config, string and dynamic references, registries and public API. Static analysis can't see reflection, so use coverage or production traces where they exist, and name what you couldn't rule out.
- **Some things don't get simplified away:** input validation at a trust boundary, handling that stops data being lost, security checks, accessibility, integrity guards, and compatibility paths outside callers use. A check is redundant only once you've traced every caller.
- **Removing a test needs proof.** Name the assertion that still covers what it protected. To replace a misleading test, plant a realistic bug: the old test should pass on it and the new one should fail. Tests that look alike aren't duplicates.
- **Trace before you inline.** A private option every caller sets the same way can go once you've checked them all, and its behavior stays, unconditionally. Two similar bodies don't justify a new abstraction, and a flag that selects between them is worse than the copies.
- **A comment explaining something surprising** usually means the code should be clearer. Fix the code, then drop the comment. If you aren't sure, keep it and flag it.
- **One kind of smell per pass.** If a pass fails its check and the cause isn't quick to find, undo it. Code whose behavior you can't pin down gets reported, not cleaned.
- **Don't approve your own risky cleanup.** Anything that could change behavior goes to a fresh reviewer where the host has one, and otherwise gets a labeled self-review. A second pass needs new evidence, such as a caller you hadn't seen, a counterexample or a runtime probe. Rerunning the same search adds nothing.

Report what you read and left alone separately from what you never examined.

## Doing a batch

- `occam ledger next --owner NAME` returns a batch from one file and marks it in progress, so concurrent agents don't collide. On a shared tree, `occam coord claim` before editing and release after.
- Make the smallest correct change. Fix the root cause in the responsible component and every caller sharing the defect, rather than a wrapper around it.
- Tier A: `occam fix` shows a diff, and `occam fix --apply` writes it. Python only, and narrow on purpose: by default it removes only brief comments that are plainly an assistant talking and give no reason, which it can prove changed no code. It refuses files with uncommitted work or another agent's claim, and won't overwrite a file that changed underneath it. `--rule unused-import` and `--rule commented-out-code` go further, but a proof of the edit isn't a proof the import was unneeded, so run the tests afterward and read its "check by hand" notes. The project's linter usually removes imports better. Everything else, including every other language, you fix by hand.
- Run the checks that this batch could affect, plus `occam gate` on the result.
- `occam ledger set --ids ... --status fixed --note "what changed and how you checked"`. Rerun `occam ledger sync` to confirm the finding is gone, not merely marked.
- Commit only if the user asked for it. Stage only your own files.
- After three failed attempts at one finding, or if fixing it keeps moving the defect, stop and question the diagnosis.

## When you find something new

Mid-repair you'll find more. Log it (`occam ledger sync`, or a note), finish the current batch, and don't widen the diff. The correction table in `occam` decides what to do: fix what's yours and small, ask about what changes behavior, and always surface a possible incident at once.

## Stopping

Stop when the agreed tiers and scope are done and verified, or when what remains needs a decision. Say which. "Everything is fixed" is almost never true of a real codebase, so report what remains and what you'd do next. Then `occam baseline write`. For a ratchet in CI, if the user wants one, commit `occam baseline write --out FILE` and run `occam scan --baseline FILE --fail-on high` there.
