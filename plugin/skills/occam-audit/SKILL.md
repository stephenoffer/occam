---
name: occam-audit
description: Audit and repair existing code, especially AI-generated code, at any size from a notebook cell or pasted snippet to a large monorepo. Use when asked to audit, assess, harden, clean up, deslop or fix a codebase, a vibe-coded app, a module or an agent's output, to find what's wrong with it, or to pay down its debt. Audit-only requests stay read-only. Not for building a new feature or reviewing one small diff, which occam covers.
---

# Occam audit

Find what is actually wrong with code that already exists, say so with evidence, repair what you're allowed to, and ask about the rest. `occam` applies here too, so load it first if it isn't loaded: its authorization, evidence and honesty rules hold in every step.

Tools are in the `occam` skill's folder, at `scripts/occam.py` (from here, `../occam/scripts/occam.py`). They use only the standard library and need Python 3.9 or later. `scan`, `map`, `reuse`, `deps` and `fix` never run or import the code they read. `golden`, `mutate`, `bench`, `goal verify` and `tools --allow-exec` do run things, so read what they'll run first. Below, `occam X` means `python3 <that path> X`.

## Done means

An audit is done when:

- Every finding you report has a location, the input or state that triggers it, what goes wrong and your evidence. A scanner hit you didn't confirm is labeled a lead.
- You ran `occam scan`, even if you read every line, went through each category in its summary, and confirmed or dismissed every critical and high lead. Say how many others you skipped.
- You read the paths where input, money, auth, tenancy and data writes meet. On code too large to read, take the riskiest and name the rest. "Not checked" is for what you couldn't reach, not what you didn't get to.
- You state the assumed workload, because scale problems only mean something against one.
- You state what you did not read or could not run. An audit that claims more coverage than it had is worse than a short one.
- If you repaired anything, each batch was verified, and you listed every change to what users see or pay, separately from the list of fixes. No behavior changed that a stated rule or a person didn't settle.
- Everything your report calls fixed has its change in the diff, and a test it says you added exists. Reread the diff against the report and rerun `occam scan` last.

## Authorization

- **"Audit", "assess", "what's wrong with":** read-only. Findings go in the report. `scan`, `map`, `reuse` and `deps` change nothing, and the tools keep their state outside the repository.
- **"Fix", "clean up", "harden":** you may apply tier A and tier B repairs inside the stated scope. Tier C always needs a person.
- **Unsure which it is:** audit first, then ask. That loses nothing.

| Tier | What it is | Who decides |
|---|---|---|
| A | Mechanical, with a proof the edit did only what it says: `occam fix`, Python only | You, once fixing is authorized. Show the diff in your report. |
| B | Corrective or behavior-preserving, like bound parameters, a timeout, or removing a clone | You, once fixing is authorized and a check protects it. |
| C | Changes behavior no document settles, a public contract, schema or stored data, cost or dependencies, or needs a product judgment | The user. Prepare it, recommend, then ask. |

A tier is the rule's default. Raise it when your reading shows more at stake, and never lower it to avoid asking.

**A stated rule settles it.** When the README, a spec or a test states the behavior and the code disagrees, restoring it is a correction, tier B, even when money is involved. Fix it and list the visible change. Anything authorized that you leave open needs a reason an owner would accept.

**Secrets.** Move a committed secret into configuration, say if something now needs a value supplied, and tell the user at once that it needs rotating, which you can't do.

## Moves

Work these in order, skipping what the size makes pointless. Start with `occam map`, which gives the tier, the worst leads, the risky files, the layers involved, other activity, and how many agents the work justifies.

1. **Check who else is here.** `occam coord status`, which reads git safely. Uncommitted changes and recent commits may be someone's work in progress. Don't reset, stash or overwrite them, and say if the audit may be chasing a moving target.
2. **Establish what it's supposed to do.** Read the README, entry points, tests and any stated requirements. If nothing states the workload or the main behaviors and a wrong guess would change your priorities, ask one question now. Otherwise state your assumption and go on.
3. **Run what exists first.** `occam tools` shows the project's own analyzers and established ones. Their results outrank occam's where they overlap, so run the project's linter, types and tests. A red baseline is itself a finding. Installing a new tool is the user's call.
4. **Scan,** at every size, since `map` shows only the worst ten leads. `occam scan`, then `occam ledger sync` once findings need tracking across agents or sessions. Output is bounded, and the full results are saved, so read the summary before opening them. Use `--min-confidence low` when hunting in one area.
5. **Read by risk.** The scanner can't see wrong business logic, and that's where the costliest defects live. Read the paths where input, money, auth, tenancy, data writes, background jobs and shared state meet, fully, whatever the scanner said about them. `occam query` lists them (`boundaries`) and traces them (`find`, `impact`). Trace one real request or job end to end.
6. **Confirm before you report.** A finding becomes real when you can name the input that breaks it, or show by reading that nothing guards it. Check dead code against dynamic references, public API and config. Mark the rest false positive with a reason: `occam ledger set --ids ... --status false-positive --note "..."`.
7. **Cover the layers.** For each layer `occam map` marks as involved, say what you checked. From user-facing behavior down to hardware, work downward only as evidence justifies, and name any layer you didn't examine.
8. **Report, ranked by what to fix first,** following [reporting](references/reporting.md).
9. **Ask, then repair in batches,** following [repair](references/repair.md). Afterwards, `occam baseline write` so new problems stop accumulating while old ones are paid down.

## What AI-generated code gets wrong

The scanner has a rule family for each of these, in `occam rules`. Its blind spots are why you still read.

- **Unfinished work that looks finished:** stubs, elision markers, checks that always return true, mock data on a real path, code nothing calls.
- **Things that don't exist:** invented packages, methods, or helpers it assumed it had written.
- **Failures hidden to look stable:** catch-all handlers that drop errors, defaults returned on failure, retries that mask a cause.
- **Tests that can't fail:** no assertions, tautologies, mocking the subject, only happy paths. `occam mutate` shows which behavior nothing protects.
- **Repetition instead of reuse:** the same helper written four ways, near-copies that have drifted so they now disagree, base classes ignored.
- **Structure with no reason:** abstractions with one implementation, factories with one product, layers that only forward, options nobody passes, impossible checks.
- **Not built for the stated load:** in-process state that breaks with a second worker, N+1 calls, unbounded results and concurrency, blocking calls on an event loop.
- **Security by imitation:** interpolated SQL, a route missing the guard its neighbors have, disabled verification, secrets in source, fail-open checks.
- **Residue:** comments addressed to the reader, `_v2` and `_final` names, stale reports, stray debug output.

## Size changes the method

Details and agent counts are in [scale](references/scale.md).

| Size | Approach |
|---|---|
| Cell or snippet | `occam scan --stdin` or the `.ipynb` file. Read every line, and fix in place if asked. No ledger, plan or subagents. |
| File or small repository | Scan everything, then read entry points and risky paths fully. One fresh reviewer at most. |
| Medium | Scan and rank, then split reading with `occam partition` across read-only agents, one per shard it prints. Use the ledger. |
| Large or monorepo | Baseline and ratchet first. Audit the riskiest subsystems and name what was left out. Repairs go in small, independently reviewable batches, never one rewrite. |

## Language and framework depth

The `occam-*` language skills cover what each language gets wrong, so load the one that matters: `occam-python` has Python's tools and traps. The scanner parses Python fully and uses text and brace-level rules elsewhere, so lean harder on `occam tools` and your own reading for other languages.
