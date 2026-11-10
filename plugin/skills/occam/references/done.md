# Done means

The switch for this turns on once a check has run on work beyond a small change, whether it passed or not.

A small change needs a relevant check on the final state and an honest report. Beyond that:

- Every acceptance condition has suitable evidence, or the user approved changing it.
- It's connected and exercised through the real entry point: callers, registration, exports, configuration, migrations, packaging, documentation.
- Checks ran on the final state. Rerun what your last edit could invalidate.
- Regression tests fail on a temp copy (`git archive HEAD`, not `git stash`), in their own command, for the intended reason.
- The repository's formatter, linter and type checker ran on what you changed, and you triaged the output.
- Pre-existing failures, unavailable environments and skipped tests are named separately.
- Known material defects are resolved or escalated, not buried.
- "Production ready", "secure" and "scalable" appear only with their scope and evidence.
