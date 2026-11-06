# Verification

## Tests that can disprove correctness

Derive tests from requirements, known failures, invariants and component contracts. Separate what the product should do from what the current code happens to do: a test that restates the implementation proves only that the code agrees with itself.

Take expected values from the requirement, a hand calculation or a reference, not from running the code and pasting what it printed. Code and test written by one author share one understanding of the problem, so aim the test at what that understanding could have got wrong.

Test public behavior and meaningful boundaries, not private implementation shape, unless that shape is the requirement. Use deterministic fixtures where possible.

Avoid a universal coverage target, a fixed test count, and redundant tests for trivial code. Don't force test-first work on mechanical or documentation-only changes.

## Choosing test types

| Risk | Consider |
|---|---|
| A rule across many inputs | Property-based tests. If no meaningful property exists beyond restating the code, say so and don't force one. |
| Two implementations should agree | Differential tests against the old code or a reference |
| Output hard to predict but relations are known | Metamorphic tests |
| Parsers and untrusted input | Fuzzing, malformed and oversized cases |
| Parts that must work together | Integration or contract tests, including features combined with one another, since each can pass alone and fail together |
| Failure handling | Failure injection: timeouts, partial failure, permission denied, cancellation, recovery |
| Throughput and limits | Load tests against a stated workload |

Consider empty, null, malformed, boundary, oversized, duplicate, concurrent and permission-denied cases. Include Unicode, timezones, precision, ordering and platform differences when they can break the contract.

**Show a critical test can detect its failure.** For a bug, the regression test fails on the buggy version for the intended reason. Show that with an isolated checkout or fixture, never by reverting another contributor's changes. Where it matters, use targeted mutation testing or a deliberately faulty implementation.

## What each kind of evidence proves

**Mocks** isolate a boundary and can't prove the integration across it. A mocked database or HTTP response may encode the same wrong assumption as the code, so both agree and both are wrong. Validate important adapters against the actual protocol, a vendor sandbox or a representative environment. If none is available, name exactly what is unverified and still run what is feasible.

**Passing suites:** check discovery, exit status, skips, warnings and which environment ran. Zero collected tests isn't a success. Distinguish a test failure from an unavailable dependency, an environmental outage and a pre-existing defect.

**Passing tests aren't the requirement.** Tests can pass while the combined behavior a user needs is broken. Exercise the real thing:

- **CLI and API:** installation or startup, help and discovery, input validation, outputs, errors and recovery.
- **UI:** actual user flows, plus empty, loading and error states.
- **Libraries:** imports and public exports from a built artifact when packaging is affected.

Don't leave verification to the user that you could do yourself.

## When a check fails

Read the earliest error in the first failing run, not the loudest or the latest. Later errors are often its consequences. Go back to the first step that was wrong, because a fix stacked on a wrong step compounds, and agents rarely notice their own first mistake. Back out attempts that didn't work before trying the next, and keep a short list of what has been ruled out so it doesn't come back.

If you notice a way to pass without doing the work, such as a leaked answer, a fixture you could special-case, a threshold you could lower or the harness itself, don't take it. Report it.

A result that varies between runs isn't a pass. Rerunning until green, adding retries and sleeping all hide it. Say it is flaky, and find the cause or report the failure rate you measured.

## Changing tests

Tests can be wrong or outdated. Change one only when intended behavior gives an independent reason, and explain it. A failing test you didn't cause gets reported, not relaxed. Mocks that encode an obsolete contract should be corrected, not deleted.

## Keeping evidence valid

For material checks, retain enough to reproduce and interpret: purpose, exact command or procedure, revision or relevant diff, environment, result or exit code, limitations. Use CI artifacts or task notes rather than inventing a receipt system.

| Status | Means |
|---|---|
| verified | Ran on the relevant state and passed |
| failed | Ran and failed |
| blocked | Couldn't run, for a stated reason |
| not run | Didn't try, or only proposed it |

Evidence stays usable while the code, configuration, dependencies and environment that matter are unchanged. An edit invalidates checks it could affect, including a final cleanup and including earlier review approval. Rerun those, not everything, and don't rerun expensive suites merely because another message arrived. Run repository-mandated checks, and broaden based on impact.

Report implementation completion and verification completion separately when they differ.

## What goes in the report

Your report is a claim, and readers act on it. Reports also tend to leave out most of what an agent did.

- **Numbers come from a run of the code you are delivering.** Copy counts from the output. Give the raw before and after from the same command, not only the ratio. Label anything else an estimate.
- **Say what you did beyond the diff:** installs, deletions, configuration and data changes, and any test you changed, with the reason.
- **Say what you read.** "Reviewed the module" means you read all of it, or you name what you skipped.
- **Keep the caveats.** A summary that keeps the headline and drops the limitation found underneath it is a false summary.

## Review findings

Look for concrete counterexamples, and separate confirmed defects, plausible concerns and style preferences. For each material finding, give:

- **Location:** file and line, or the interaction.
- **Failure scenario:** the input or state, and what goes wrong.
- **Evidence:** what you ran or read that supports it.
- **Impact:** who is affected and how badly.
- **Correction and verification:** what would fix it and how to confirm that.

When reviewing someone else's change, say what you examined and what you didn't. Check how a change behaves under real configuration and defaults, not just the branch the diff highlights. A static-analysis finding is a lead until its exploit or failure conditions are confirmed. A clean review is an acceptable result, so don't manufacture a quota.

When briefing a separate reviewer, give requirements, constraints, relevant source or diff, and test evidence. Ask separately about requirement coverage and engineering quality. Don't prime it with claims that the design is correct, and treat what it returns as claims to inspect. A clean review from the same kind of model is weak evidence: it shares the author's blind spots and usually misses an agent's first mistake, so it doesn't replace an executable check.
