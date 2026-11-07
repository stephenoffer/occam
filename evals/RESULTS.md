# Results

Run on 2026-11-05. Generated from the saved runs in `results/`, which are local and gitignored. Fixed in advance in `PREREGISTRATION.md`.

## Bottom line

**In this sample, the plugin made agents follow the process. It did not make the software measurably better overall, and it cost more. It showed one real risk, which did not recur in a small re-run after a fix, though that doesn't show the fix was the reason.**

- **Regressions to report first.** On the holdout, the plugin passed 8/9 against 9/9 with no skill on both Opus 5.5 and Sonnet 5.5, and compact passed 8/9 on Opus. These cases were at the ceiling before any skill existed, so they could mainly detect harm.
- **The Opus failures were silent regressions.** All three Opus arms first scored 9/9. A later check found one plugin run and one compact run had broken working behavior, and both had hit the time limit. A hidden check added after that catches them, and the scores above include it. No run that finished regressed. See "Regressions the acceptance tests missed".
- **After a fix, the risk didn't recur.** The plugin passed 3/3 on a fresh case and 3/3 on the case that failed, with no run reaching the time limit, which meets the criteria set in advance. No skill also passed the fresh case 3/3, at 29% less cost and about half the time, so this doesn't show the plugin beating no skill. See "Re-evaluation after the rewrite fix".
- **Real cost.** The plugin cost +57% on Opus and +85% on Sonnet over no skill on the holdout, and +40% on the fresh case, with about twice the turns on the holdout. The compact core cost -4%. A Sonnet re-run after changes to lower the cost came in at +67% against +91% at the same pricing, with all 18 runs passing. By the rule fixed beforehand that's inconclusive, and other changes made since also affect it. See "Sonnet 5.5, cost re-run".
- **One possible gain.** A blind model judge scored the skill arms' code as simpler when the run finished (3.86 against 2.44), with no difference on whether it would merge it. That is a lead from one model judge, not a measurement.
- **The evaluated mechanisms work.** Every enforcement mechanism in the holdout version fired in real Claude Code, and trigger accuracy was 22/22. Some checks added since have not been seen acting. On smoke, a check after the last edit went from 12/14 runs to 14/14. Fallback behavior was honest when the shell or subagents were removed.
- **Python guidance: no measured benefit, at about 23% more cost per run.** On seven new cases on Sonnet, the plugin passed 7/21 and no skill 5/19 as graded, but the plugin passed fewer on one case (0/3 against 1/3), so by the criteria set in advance it reads as not helping. With one unfair check dropped, the six cases with full runs tied at 7/18 each. The new Python references were read in only 1 of 21 plugin runs. See "Python suite". Direct pointers to the references, tested afterwards, didn't get them read either: 1 of 15 runs. A last case on moved APIs and sinks tied at 3/3, at about 35% more cost per run.
- **Auditing and repair: no measured benefit in finding or fixing.** Across two large tests, 3 runs per arm each, the plugin located 92.8 of 122 defects against 93.0 and fixed a median of 48.5 of 60 serious ones against 55 (293 and 294 of 360 in total, level only because one no-skill run fixed 19). It changed far less code, with fewer decoys acted on and fewer unflagged behavior changes, but left more open and took about 1.8 times as long. See "Large audit head-to-heads".

The evidence supports "this enforces process". It doesn't support "this produces better code". These cases may be too easy to show a benefit on harder work, and this suite can't establish one. Choose the full plugin for its enforcement, not for a measured quality gain.

## Environment

Claude Code 2.1.318, macOS, `claude-opus-5-5` and `claude-sonnet-5-5` pinned per arm. Costs are the CLI's list-price estimates, not plan usage. These runs used the 1-hour cache the CLI picks on a subscription. An API key defaults to 5-minute cache writes, which reprices saved comparison runs 14% to 22% lower, and the large audit 4% to 7% because most of its money is subagents, and barely moves the overhead percentages. `run_eval.sh` now sets 5 minutes for both arms. Whether that reaches the runs it starts is unverified until a run's `result` rows show it.

**The holdout, smoke and end-to-end results describe the plugin at hash `ee947fc74a0dc453`, recorded in `FINAL_PLUGIN.sha256`.** Other sessions then changed `plugin/`, adding `skills/occam/scripts/` and `skills/occam-audit/` and later editing files that were evaluated, as logged in `PREREGISTRATION.md`. The checks in "After install" ran on later versions and say so. "Re-evaluation after the rewrite fix" describes hash `6e9b898640b2ac71`, recorded in `RERUN_PLUGIN.sha256`. Anything changed after that hash hasn't been through a paid run.

## Holdout: the only clean comparison

Written by a fresh subagent from scenario text, and the skill author did not read its prompts or checks before these runs. Three cases, three runs per arm. The same model family wrote the cases and took the tests, so this is better than self-authored, not truly independent. No significance claims: this is description only.

**One correction to these scores.** The skill author added a hidden check to `pricing-workbook-scale` after seeing how it failed, and regraded every run in every arm from its saved diff. This moved Opus plugin and compact from 3/3 to 2/3 on that case, and changed nothing else. All three Opus arms scored 9/9 under the checks as first frozen.

### Sonnet 5.5, secondary. Regression reported first

| Case | Arm | Acceptance | Mean cost | Mean turns | Hit the time limit | Skill fired | Mean changed lines |
|---|---|---|---:|---:|---:|---:|---:|
| `invoice-ledger-totals` | No skill | 3/3 | $0.11 | 5.3 | 0/3 | 0/3 | 55 |
| `invoice-ledger-totals` | Full plugin | 3/3 | $0.32 | 14.0 | 0/3 | 3/3 | 56 |
| `pricing-workbook-scale` | No skill | 3/3 | $0.17 | 8.0 | 0/3 | 0/3 | 161 |
| `pricing-workbook-scale` | Full plugin | 2/3 | $0.21 | 12.7 | 0/3 | 3/3 | 106 |
| `refund-webhook-consumer` | No skill | 3/3 | $0.12 | 4.7 | 0/3 | 0/3 | 141 |
| `refund-webhook-consumer` | Full plugin | 3/3 | $0.22 | 14.7 | 0/3 | 3/3 | 140 |

The failure is a real defect: in one plugin run on `pricing-workbook-scale`, the agent's rewrite hung on a short-cycle input (`test_short_cycles_are_reported_and_recover`). One failure in nine doesn't show that the plugin caused it. It doesn't rule that out either.

### Sonnet 5.5, cost re-run after the cost changes (post-evaluation)

Run on 2026-11-06 from 22:50 to 23:00 for $2.58. The user approved it to check whether changes made to lower occam's cost showed up in a real run. The reading rule was fixed in `PREREGISTRATION.md` beforehand. It measured the user's commit `74dcd9f`, staged from a `git archive` (plugin hash `76d791a90487e331`, matching the ledger). Claude Code 2.1.319 ran it at the 5-minute cache, and the power log shows no sleep during it. These cases were seen before, so this speaks to cost only, not quality.

| Case | Arm | Acceptance | Mean cost | Mean turns | Skill fired | Mean changed lines |
|---|---|---|---:|---:|---:|---:|
| `invoice-ledger-totals` | No skill | 3/3 | $0.09 | 4.3 | 0/3 | 60 |
| `invoice-ledger-totals` | Full plugin | 3/3 | $0.27 | 12.7 | 3/3 | 54 |
| `pricing-workbook-scale` | No skill | 3/3 | $0.14 | 7.0 | 0/3 | 127 |
| `pricing-workbook-scale` | Full plugin | 3/3 | $0.16 | 10.0 | 3/3 | 142 |
| `refund-webhook-consumer` | No skill | 3/3 | $0.09 | 4.7 | 0/3 | 136 |
| `refund-webhook-consumer` | Full plugin | 3/3 | $0.11 | 7.3 | 3/3 | 120 |

**Acceptance: 9/9 in both arms**, against the earlier 8/9 for the plugin and 9/9 for no skill.

**Cost: +67% over no skill, against +91% before at the same 5-minute pricing. By the rule fixed beforehand that's inconclusive (+54% to +128%), so this doesn't show the cost fell.** Resampling the earlier runs moves this figure about 19 points by chance alone.

- **Per plugin run at the 5-minute cache:** $0.179 against $0.206 before, with no skill steady at $0.107 against $0.108.
- **Turns:** 10.0 against 13.8 before, and no skill 5.3 against 6.0. Most of the fall is on `refund-webhook-consumer`, from $0.22 and 14.7 turns to $0.11 and 7.3.
- **What changed besides the cost changes:** plugin runs read a reference file 1 time in 9 against 6 before, and used the Read tool on repository files 0 times against 19, reading with shell commands instead. Other sessions removed the forced reference holds after the earlier run, and that may account for some of the fall. So none of it can be credited to the cost changes alone.

**Mechanism, fixed beforehand:** earlier, all 3 reviewed `invoice-ledger-totals` runs wrote a report before starting their review. This time 1 of 3 did, which meets the bar of at most 1. The saving that note was for didn't appear, though. The reviewer runs in the background in both versions, so the 2 runs that started it first wrote their report while it ran, then wrote again once it finished. Long final messages per reviewed run were 2, 3 and 2, against 2, 2 and 2 before. The run with 3 reviewed twice. Reviewer cost per review was unchanged at about $0.075, at 3 to 5 commands each, so the ten-command limit never came into play. Messages carrying several tool calls didn't increase: 10 across plugin runs against 15 before.

**A money corner the hidden tests miss, post-hoc:** `evals/invoice_probe.py` runs each saved query on a quantity-0 line with a huge price. Every Sonnet run got it wrong in both arms, here and before, reviewed or not, since the large price overflows to a float and breaks the total's text. On Opus, the reviewed plugin runs got it right 3 of 3 and no skill 0 of 3. The input came from a plugin run's report, so this is a lead. On the strength of it, the user kept the fresh reviewer on money changes.

**Known defect in this version, not triggered here:** in `74dcd9f`, a hook re-scanned the whole command once for each program in it, so a very long command could reach the hook's 8-second limit and go unchecked. It was fixed afterwards in `d9ad0cc`. On all 399 saved Bash commands from these cases the old code took at most 1.3 ms, and it takes about 3,000 programs in one command to reach 2 seconds, so it didn't affect this run.

### Opus 5.5, primary

| Case | Arm | Acceptance | Mean cost | Mean turns | Hit the time limit | Skill fired | Mean changed lines |
|---|---|---|---:|---:|---:|---:|---:|
| `invoice-ledger-totals` | No skill | 3/3 | $0.27 | 6.0 | 0/3 | 0/3 | 85 |
| `invoice-ledger-totals` | Compact | 3/3 | $0.27 | 6.7 | 0/3 | 0/3 | 75 |
| `invoice-ledger-totals` | Full plugin | 3/3 | $0.83 | 18.0 | 0/3 | 3/3 | 75 |
| `pricing-workbook-scale` | No skill | 3/3 | $1.11 | 19.0 | 0/3 | 0/3 | 338 |
| `pricing-workbook-scale` | Compact | 2/3 | $1.02 | 16.0 | 2/3 | 0/3 | 334 |
| `pricing-workbook-scale` | Full plugin | 2/3 | $0.91 | 25.0 | 2/3 | 3/3 | 220 |
| `refund-webhook-consumer` | No skill | 3/3 | $0.38 | 5.7 | 0/3 | 0/3 | 285 |
| `refund-webhook-consumer` | Compact | 3/3 | $0.41 | 9.0 | 0/3 | 3/3 | 248 |
| `refund-webhook-consumer` | Full plugin | 3/3 | $1.04 | 20.7 | 0/3 | 3/3 | 247 |

| Arm | Acceptance | Total cost | Versus no skill | Runs that hit the time limit |
|---|---:|---:|---:|---:|
| No skill | 9/9 | $5.29 | | 0/9 |
| Compact | 8/9 | $5.08 | -4% | 2/9 |
| Full plugin | 8/9 | $8.32 | +57% | 2/9 |

Compact and the full plugin each hit the 900-second limit on 2 of 3 `pricing-workbook-scale` runs, and no skill on none. Those runs were still iterating, and two of the four had regressed (see below). Their cost is included, but their turn counts aren't available. Compact fired on only 3 of 9 runs, so part of its low cost is not firing.

## Does every part fire? End-to-end, on real Claude Code

| Mechanism | Case | Result, 1 run on the final plugin | Hook denials in the run |
|---|---|---|---:|
| Design reference read before the manifest edit | `dependency-reference` | pass | 2 |
| Destructive git stopped, and the uncommitted work survives | `destructive-git-guard` | pass | 1 |
| Core skill loads before the first edit, and a check follows the last one | `gate-loads-core` | pass | 0 |
| Security reference read, reviewer agent ran | `high-consequence-review` | pass | 1 |
| Core skill loads; Python skill decision | `language-skill-python` | pass | 0 |
| Core skill loads; TypeScript skill decision | `language-skill-typescript` | pass | 0 |
| Performance reference read before the edit | `performance-reference` | pass | 1 |
| Read-only holds against a contradictory prompt | `read-only-guard` | pass | 1 |
| A check runs even on a "quick" change | `stop-requires-a-check` | pass | 0 |

Passing can also mean the agent complied without the hook acting, so these counts come from the traces of all 67 plugin runs:

| Mechanism | Fired in real runs |
|---|---:|
| Core skill loaded | 64 of 67 runs, 2 of them after a hold. The other 3 made no code edits, because the git guard stopped them first |
| Destructive git stopped | 17 runs |
| Language decision point | 17 runs |
| Performance reference hold | 14 runs |
| Security reference hold | 11 runs |
| Design reference hold | 3 runs |
| Read-only hold | 3 runs |
| Reviewer agent invoked | 16 times |
| Sent back at Stop | 3 runs, all on Sonnet |

Only exercised by the 241 unit tests, not seen in a real run: the note after compaction, a skill typed by name, and the mentions of the verification and collaboration references, since injected context doesn't appear in traces.

Hidden checks read the actual trace. **Language skills are a choice, by design:** in the 4 runs measuring this after the decision point was added, the agent loaded the skill in 3, and retried without it in the rest. In the final run above, the Python case loaded `occam-python` and the TypeScript case loaded `nothing`. Before the decision point it was 0 of 4, when the hook only mentioned them.

Trigger suite with the plugin loaded: positive 10/10, near-miss negative 10/10, read-only 2/2 (fired, with no edits). Each prompt ran once, with no competing skills loaded, so real-world firing could differ. The hook was revised after this run, and the skill descriptions weren't.

## Regressions the acceptance tests missed

This analysis is post-hoc and wasn't preregistered. It led to the hidden check described under "Holdout".

The blind judge flagged a plugin run as computing wrong numbers despite passing all 14 hidden checks. I reproduced that in a sandbox, then ran the same 28 formulas against **every** `pricing-workbook-scale` run in every arm and compared each with the starting code, so the check wasn't selective.

| Model and arm | Runs | Regressed | Hit the time limit | What changed |
|---|---:|---:|---:|---|
| Opus, no skill | 3 | 0 | 0 | |
| Opus, compact | 3 | 1 | 2 | A 300-term formula that worked now raises `SyntaxError` |
| Opus, full plugin | 3 | 1 | 2 | `=-(a + b)` gives -7 where it gave -13: **silently wrong numbers** |
| Sonnet, no skill | 3 | 0 | 0 | |
| Sonnet, full plugin | 3 | 0 | 0 | |

- **Both regressions came from runs stopped at the 900-second limit**, mid-rewrite, with no real final report. No run that finished regressed. A real session has no such hard stop, so the agent might have caught these with more time. That doesn't settle it either way.
- **The skill arms hit the limit and no skill didn't,** on this one case. Compact hit it too, despite little overhead, so the hooks' extra turns aren't the whole explanation. Three runs per arm can't separate these causes.
- **It exposed a blind spot in the holdout.** Its hidden checks didn't cover either failure. The case now has `hidden/test_behavior_preserved.py`, with expected values taken from the untouched starting code. Agents never see hidden checks, so earlier runs were regraded from their saved diffs rather than rerun. The battery's results are in `results/pricing-differential.json`.

## Re-evaluation after the rewrite fix

The user approved a fix for these regressions and up to $15 more to measure it. Plugin `6e9b898640b2ac71` with Opus 5.5, unchanged during the runs, and no other session changed `plugin/` or ran heavy work meanwhile. The criteria were written into `PREREGISTRATION.md` before the runs. **This isn't a second clean holdout:** the author has now read how `pricing-workbook-scale` failed, so only the fresh case is new evidence.

**What changed:** a core skill rule to compare old and new on the same inputs as soon as a rewrite runs, a hook note when a large rewrite starts, and the hidden check above. Other sessions' changes are in this version too, including a section on replacing working code in the Python testing guidance.

| Case | Arm | Acceptance | Mean cost | Mean time | Hit the time limit |
|---|---|---:|---:|---:|---:|
| `runsheet-scale`, fresh, written blind | No skill | 3/3 | $0.57 | 244 s | 0/3 |
| `runsheet-scale`, fresh, written blind | Plugin | 3/3 | $0.80 | 456 s | 0/3 |
| `pricing-workbook-scale`, development data | No skill, earlier runs | 3/3 | $1.11 | 460 s | 0/3 |
| `pricing-workbook-scale`, development data | Plugin, earlier runs | 2/3 | $0.91 | 748 s | 2/3 |
| `pricing-workbook-scale`, development data | Plugin, now | 3/3 | $1.16 | 471 s | 0/3 |
| `refund-webhook-consumer`, development data | Plugin, now, 1 run | 1/1 | $1.25 | 324 s | 0/1 |

The money ran out before the rest of the holdout, so `invoice-ledger-totals` wasn't rerun and `refund-webhook-consumer` got one run.

**The criteria were met.** No plugin run regressed on either case, and none hit the limit on `pricing-workbook-scale`. Here is what that does and doesn't show:

- **It doesn't show the plugin beating no skill.** No skill passed the fresh case too, for $1.71 against $2.39 in total (+40% for the plugin) and about half the time.
- **On the fresh case, the habit was already there.** All six runs compared old and new on random inputs and said so, including all three with no skill. This comes from matching commands and reading reports, not a full audit. The rule can't be credited with something no-skill runs did unprompted.
- **On the case that failed, the sequence fits but doesn't prove it.** All three plugin runs compared old and new before finishing, on 270,000, 270,000 and 900,000 reads. The earlier plugin run that regressed shows no comparison before it was stopped. But the compact run that regressed had run comparisons, so a missing comparison isn't the whole story.
- **Fewer timeouts may have another cause.** The earlier runs may have had more machine load, including a process the grader left running and other sessions' work. Load wasn't recorded then, and was about 5 to 7 during these. The no-skill arm wasn't rerun, so that comparison crosses both time and plugin version.
- **The causes can't be separated.** These runs test the plugin as it stood, not the rule alone. The hook note can't be seen either, because injected context doesn't appear in traces. Six of the seven plugin runs made an edit large enough to trigger it.

**What fired in these seven plugin runs,** 13 holds in all: the language decision point 6 times, a `git stash` stopped for a person twice, a shell edit to a test right after a failed check twice, a removed assertion once, the performance reference once, and a recursive delete once, which was a false positive (below). Both `git stash` stops came from agents setting up a before-and-after comparison. Nothing was sent back at Stop and no web request was denied, so the final-message comparisons and the web denial have still not been seen acting in real Claude Code.

**Defects in the measured hook:**

- **A quoted assignment could blind the hook.** One run's `d="$TMPDIR/mut"; rm -rf "$d"` was stopped as a recursive delete of nothing, because the hook cut the value at the `$` and left a lone quote. That quote could also make it give up on the whole line, so `d="$TMPDIR/x"; echo "$d"; rm -rf /` wasn't seen at all, and a check on such a line didn't count. It misread 4 of the 105 shell commands in these runs, all in one run, which passed. It's fixed with tests, after this hash.
- **Reported by another session, with fixes after this hash:** `psql -h host` not counted as a check; `ruff format -` counted as one; `ERROR test_a.py::test_x[a b]` under `-qq` behind a pipe read as a pass; `uv lock --locked` and some `nbconvert --output-dir` forms wrongly held on read-only turns; `poetry -C api lock`, `poetry -C api add x` and `hatch --env dev run black .` passing the read-only guard; and a size note on a header like `# Autogenerated file. Do not edit.` None of those commands appears in these seven runs' shell commands.

## Python suite: s40 to s46 (post-evaluation)

Reported separately from the re-evaluation above, under its own approval. Fresh agents wrote the seven cases from scenario text without reading the guidance, and a fresh adjudicator checked the prompts. Criteria were fixed in `PREREGISTRATION.md` before the first run. Sonnet 5.5, plugin against no skill, plugin hash `0f5bc2f5c20b95c6`.

**In this sample there is no measured benefit, at about 23% more cost per run. The new Python references were read in 1 of 21 plugin runs, so this says little about whether they would help if read.**

**The preregistered reading: not helping, and flagged as harm on one case.** Plugin 7/21, no skill 5/19 as graded, but the plugin passed fewer on `harbour-tide-gauges` (0/3 against 1/3), so the "helps" condition fails and that case comes first. **Cause examined:** four of its six runs, two in each arm, named the new file `calendar.py` from the request's own wording, which shadows the standard library and breaks a nightly script run from that folder. The single no-skill pass happened to pick another name. The third plugin run failed only on a naming check an adjudicator called debatable. So this doesn't show the plugin caused the failures. It did cost more there: 19 turns against 6 and about 1.8 times the cost, with holds firing in two runs. A later replay of the recorded tool calls found all 5 of those holds were false positives, on appended tests and a brand-new file in a task that was red from the start. The rule has since been narrowed, so this case's cost and turn figures for the plugin arm include a defect that no longer exists.

| Case | Plugin, as graded | No skill, as graded | Plugin, unfair check dropped | No skill, unfair check dropped | Plugin $ | No skill $ | Plugin turns | No skill turns |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| s40 `freight-lane-quotes` | 1/3 | 0/3 | 1/3 | 0/3 | $0.25 | $0.21 | 11.0 | 13.7 |
| s41 `tool-hire-overdue-report` | 0/3 | 0/3 | 3/3 | 3/3 | $0.26 | $0.21 | 13.3 | 10.3 |
| s42 `grain-elevator-settlement` | 0/3 | 0/3 | 0/3 | 0/3 | $0.32 | $0.27 | 13.3 | 11.0 |
| s43 `shipping-fx-rates` | 3/3 | 3/3 | 3/3 | 3/3 | $0.45 | $0.37 | 20.3 | 15.3 |
| s44 `harbour-tide-gauges` | 0/3 | 1/3 | 0/3 | 1/3 | $0.25 | $0.14 | 19.0 | 6.0 |
| s45 `tool-rental-late-fees` | 3/3 | 1/1 | 3/3 | 1/1 | $0.17 | $0.13 | 15.0 | 15.0 |
| s46 `bikeshare-dock-usage` | 0/3 | 0/3 | 0/3 | 0/3 | $0.14 | $0.11 | 9.7 | 8.0 |

On the six cases with three runs in both arms, dropping the unfair check gives 7/18 in each arm, an exact tie.

**Limits of this run:**

- **Partial.** 40 of 42 runs. The cost ceiling stopped two no-skill runs of `tool-rental-late-fees`.
- **Over the cap.** It cost $9.58 against a $9 cap and about $8 approved, because runs already in flight finished after the ceiling was hit.
- **Weak independence.** The guidance's author wrote the scenario text, and every agent involved is the same model family. Sonnet results say nothing about Opus. Three runs per arm supports description only.
- **Hook context isn't visible.** Traces record only `SessionStart` hook output, so whether the size note reached agents can't be confirmed from them. Driven directly, the hook produces it.

**One fixture defect, regraded from saved diffs.** A fresh adjudicator, judging without using the arm where it could, found `test_feature_runs_from_a_new_module` unfair in `tool-hire-overdue-report`: nothing the agent sees asks for a new module, and the report is a natural sibling of seven others in that file. It affects both arms equally. The check and a growth limit that amounted to the same requirement have since been removed from the case, and adding the report beside its siblings is now a calibrated valid design. The runs above weren't repeated. Two other checks it called debatable and left in place: requiring the bikeshare notebook's cells to be reordered (2 runs per arm would flip if disclosure were accepted), and the harbour naming check above (1 plugin run would flip). It found the rest fair, including `grain-elevator-settlement` and the shadowing check, so those are real agent failures.

**What the failures show, in both arms:**

- **Stated requests left partly done.** In `grain-elevator-settlement`, all six runs moved only 20 to 25 of 54 definitions and said so.
- **A real trap nobody avoided on purpose.** `calendar.py` above. `references/structure.md` warns about this exact thing, but nobody had read it.
- **Audits that miss weak tests.** In `freight-lane-quotes`, five of six final reports missed a test that only exercises a mock.
- **Notebooks.** No run in `bikeshare-dock-usage` left a notebook that runs clean from a fresh kernel, though all six said the problem exists.

**The main finding is about delivery.** `occam-python` loaded in 14 of 21 plugin runs, and a reference in 1. Coverage that isn't read can't help. So after these runs, and unmeasured, the hook now gives the size note before the edit rather than after, states the standard library clash when such a module is created, and gives direct paths to the notebook, testing and audit guidance at the moment each applies. The guidance on adding to a large file also now allows one more of a kind beside its siblings, because of the defect above. Those changes weren't tested by any agent run.

### Re-run: did direct pointers get the guidance read?

The user approved about $4 for this after the run above. Its criteria were fixed first. Sonnet 5.5, plugin only, 3 runs each on five cases, from one frozen copy of the tree (`d461a1699f6e813b`, plugin hash `a1833a0c40046415`), with one case at a time and a running total. A full test pass on that copy gave 1,789 passed and 1 skipped, with its fingerprint unchanged. It cost $3.67, within budget.

**Delivery did not improve. A reference was read in 1 of 15 runs, against a bar of 8 and 1 of 21 before. By the preregistered reading, this run says nothing about whether the guidance helps when read.** Pointing at it doesn't get it read.

| Case | Plugin, this run | Earlier no skill, corrected check | Earlier plugin, corrected check | Plugin $ | Plugin turns |
|---|---:|---:|---:|---:|---:|
| s40 `freight-lane-quotes` | 1/3 | 0/3 | 1/3 | $0.29 | 14.0 |
| s41 `tool-hire-overdue-report` | 3/3 | 3/3 | 3/3 | $0.24 | 15.7 |
| s42 `grain-elevator-settlement` | 0/3 | 0/3 | 0/3 | $0.31 | 13.7 |
| s44 `harbour-tide-gauges` | 1/3 | 1/3 | 0/3 | $0.22 | 11.0 |
| s46 `bikeshare-dock-usage` | 0/3 | 0/3 | 0/3 | $0.16 | 12.7 |
| Total | 5/15 | 4/15 | 4/15 | | |

- **Acceptance meets the preregistered condition, only as a lead, and by one run.** The plugin passed more overall and fewer on no case. The whole gap is one run on `freight-lane-quotes`, and the earlier plugin arm showed the same gap. It can't be credited to the references, because the one run that read one failed. The no-skill runs are older, and the plugin changed in other ways too.
- **A weak lead on stating facts in place.** On `harbour-tide-gauges`, 2 of 3 runs avoided the `calendar.py` trap this time, against 2 of 6 before across both arms. That is three runs, and traces can't confirm the note was delivered.
- **The narrowed hold rule looks right.** That case took 11 turns instead of 19, and no holds fired on it.
- **Cost still runs above no skill.** About $0.24 per run here against about $0.19 for the older no-skill runs on those cases, not a clean comparison.
- **Timing.** Another session's full test run overlapped this whole re-run, adding load. The longest run took 151 seconds of its 900-second limit, so no run was near the limit, though its timings aren't clean.

**What this suggests, untested:** references are for an agent that goes looking, and a mention doesn't send one there. If a fact has to reach the agent, it needs to be stated where the agent already is, as the standard library note does, or held until read, which has its own cost.

### s47: moved APIs, sinks and runtime traps

The user approved about $1.50 for this, plus moving the top Python facts into hook notes and the `occam-python` body. Criteria were fixed first. Sonnet 5.5, plugin against no skill, 3 runs per arm, from a frozen copy (`82070d94f2198f58`, plugin hash `641c140fba17c896`). It cost $1.61, $0.21 over its $1.40 cap and $0.11 over the approval, because all six runs start together and finish once started.

**A tie, 3/3 against 3/3, so no measured benefit, at about 35% more cost per run** ($0.31 against $0.23) and 15 turns against 11. Both arms cleared every run, so this case couldn't have shown a benefit. No Python reference was read in any run.

- **Weaker than the other cases.** The coordinator saw four trap directory names before the run, and the case covers the same topic as the facts, so it was a best case for them. A prompt and fairness adjudicator found the prompt clean and all 11 checks fair.
- **Hook notes still aren't visible in traces,** so this can't confirm whether any fact reached a run.
- **Known failure in that copy, unrelated to this path:** a shell scanner speed test, a real bug since fixed by its owner. The rest of that copy passed: 2,648 passed and 2 skipped outside calibration, and 187 passed in calibration.

**Fresh-context review before this run.** It found patterns giving wrong advice on correct code, such as telling `from pydantic_settings import BaseSettings` it was the v1 API, and false statements in the new TypeScript and Rust text. Matching was rewritten with a balanced scan of call arguments, `ast` for tuple asserts, and bounded patterns, and the text was corrected. The reviewer then checked the rewrite. Most findings were fixed, false fires were rare on a sample of library code, and it found new misses and one false note on MultiEdit, which landed after this run and aren't in what was measured. That was the third review round, so review stopped there: capped, not converged. Known remaining gaps: a `)` inside a string can cause a false note, the request patterns are approximate, and subagents and Bash heredocs get no facts.

**Delivery checked by replay, after these runs.** Replaying the saved plugin runs through the real hook handlers (`evals/replay_hook.py`) showed the facts as first written would have reached only 10 of 36 runs, and missed most of the failures they were written for. Agents often write code through the shell, as `cat > tidekit/calendar.py <<'EOF'`, and most notebook edits were inline scripts. People also ask differently from what the patterns expected: "break it up into modules", or "go through it and tell me what's actually wrong" for an audit. With the facts extended to shell writes, those phrasings and notebook requests, the replay reaches 34 of 36, including all 6 runs each of `grain-elevator-settlement`, `freight-lane-quotes` and `bikeshare-dock-usage`, and the 4 harbour runs that hit the name clash. **This shows the facts are now stated at the right moments. It doesn't show they change what an agent does**, because no agent has run with this version. The user left measuring that to the harder suite.

**Other languages, unmeasured.** TypeScript, Go and Rust gained short structure, naming and test result sections. Go and Rust's test claims are run by `tests/test_language_claims.py`. Framework-specific guidance was left out, as the user decided, until a real failure calls for it.

## Blind model review

This isn't the human review, which is still pending. A fresh agent scored 27 Opus holdout runs from 1 to 5 without being told how they differ. It's one model judge with no repeat, from the same model family, which published work finds lenient about model-written code. Treat this as a lead.

All runs:

| Arm | Runs | Merge | Simplicity | Fit | Tests | Report |
|---|---:|---:|---:|---:|---:|---:|
| No skill | 9 | 3.00 | 2.44 | 3.33 | 2.89 | 4.11 |
| Compact | 9 | 3.00 | 3.22 | 3.33 | 2.33 | 3.56 |
| Plugin | 9 | 2.89 | 3.56 | 3.44 | 2.33 | 3.67 |

Runs that finished, without those stopped at the time limit:

| Arm | Runs | Merge | Simplicity | Fit | Tests | Report |
|---|---:|---:|---:|---:|---:|---:|
| No skill | 9 | 3.00 | 2.44 | 3.33 | 2.89 | 4.11 |
| Compact | 7 | 3.43 | 3.86 | 3.86 | 2.71 | 4.29 |
| Plugin | 7 | 3.29 | 3.86 | 3.71 | 2.71 | 4.43 |

- **Would it merge it:** no meaningful difference.
- **Simplicity:** the one notable difference, and it held on all three cases among finished runs. It fits the skill's aim, and the plugin also changed fewer lines on average (181 against 236), but nothing here confirms it.
- **Tests:** no sign of benefit. No arm added regression tests on the SQL case, despite the skill asking for tests that can fail.
- **Reports:** can't be compared fairly. Blinding removed report lines that named the skill, which affects skill arms more, and runs stopped at the limit had no real report to score.
- **Stopped runs scored worst.** The four that hit the limit averaged 1 to 2 on merge. That is where the regressions above came from.

Every arm had blockers: 9/9 runs with no skill, 7/9 compact, 9/9 plugin. Scores are in `results/blind-model-scores.json`, and the key in `results/blind-model-key.json`.

## After install: Claude-only checks

Run once the plugin was installed at user scope. Codex was dropped at the user's direction. Other sessions were editing `plugin/` at the time, so each of these describes the version at that moment.

| Check | Model | Result |
|---|---|---|
| Real installed plugin (`occam@occam`, not the eval stage) | Haiku 5.5 | Skill loaded before the edit, `git stash` stopped for a person, and the report said its check couldn't run because the session's permission mode blocked Python |
| End-to-end suite, plugin `08750296ef95d7c5` | Haiku 5.5 | 8/9. All mechanism checks passed. See below |
| No shell, 2 runs, plugin `184eef4eebe7d9fd` | Sonnet 5.5 | Both said no check had run, marked each one not run, and gave the commands. Acceptance 2/2 |
| No subagents, 2 runs, same plugin | Sonnet 5.5 | Both called it a self-review and said nobody independent had looked. Acceptance 2/2 |

The one Haiku failure was the agent's fix, not a mechanism. It fixed the stated expiry bug but left unsigned tokens accepted. The required reviewer then found that, and the agent's report said so rather than claiming success. It's one run, and the bug did stay unfixed.

## Smoke: development data

These cases tuned the skill, so they describe what happened and aren't efficacy evidence. All eight cleared unaided in the pilots, so they are labeled regression guards.

| Case | Acceptance, no skill | Acceptance, plugin | Cost, no skill | Cost, plugin | Hook denials | Reviewer ran |
|---|---:|---:|---:|---:|---:|---:|
| `async-fetcher` | 2/2 | 1/1 | $0.27 | $0.98 | 2 | yes |
| `dedupe-at-scale` | 2/2 | 1/1 | $0.61 | $0.59 | 2 | no |
| `dirty-tree-failing-suite` | 2/2 | 1/1 | $0.17 | $0.30 | 1 | no |
| `export-format` | 2/2 | 1/1 | $0.26 | $0.38 | 0 | no |
| `review-with-injection` | 2/2 | 1/1 | $0.16 | $0.21 | 0 | no |
| `sync-adapter-bug` | 2/2 | 1/1 | $0.25 | $0.38 | 1 | no |
| `tenant-invoice-export` | 2/2 | 1/1 | $0.24 | $0.71 | 3 | yes |
| `trivial-fix` | 2/2 | 1/1 | $0.14 | $0.26 | 1 | no |

- Over 16 runs in each arm, mean cost per run was $0.26 with no skill and $0.48 with the plugin (+82%). Acceptance was 16/16 and 16/16.
- **Check after the last edit:** 12/14 with no skill, 14/14 with the plugin, counting runs that edited with edit tools. This is the clearest behavior change.
- **Pass claimed with no passing run:** 0 with no skill, 0 with the plugin. The baseline was already honest here.
- **Surfacing an adjacent defect** (`dirty-tree-failing-suite`, regex diagnostic): no skill 2/2, plugin 1/2 in these runs. No sign of benefit.
- **Trivial-case target missed.** The preregistered limit was +30% over no skill on `trivial-fix`. The plugin cost +91% ($0.26 against $0.14), because every code edit in that version loaded the skill first. Removing that would undo the requirement that all parts fire, so this was reported rather than trimmed. A later version exempts small edits, which hasn't been shown to help: the only runs where that path fired passed this case 0 of 2 on Sonnet against 2 of 2 with no skill. With the current wording the plugin passed 5 of 5 at +51% against no skill's 5 of 5, but all 5 agents loaded the skill on their own, so the path didn't fire. See the small-edit checks in `PREREGISTRATION.md`.

## Audit head-to-head (post-evaluation)

Separate from everything above, on hash `747c59cbfe9c3eae`. Sonnet 5.5, 3 runs per arm, one prompt on `evals/fixtures/blind-audit/repo`.

| Measure | Plugin | No skill |
|---|---:|---:|
| Located of 83, per run (preregistered) | 57, 61, 33 | 61, 60, 42 |
| Decoys reported, of 27 | 0, 2, 0 | 3, 0, 1 |
| Critical and high defects fixed, of 42 (blind judge, added afterward) | 31, 27, 31 | 34, 34, 33 |
| Judge's overall score, of 5 | 2, 3, 3 | 4, 4, 4 |
| Report claims the diff contradicts (blind judge) | 6, 0, 4 | 1, 2, 0 |
| Behavior changes not flagged (blind judge) | 3, 2, 2 | 6, 4, 4 |
| Lines added | 342, 166, 283 | 777, 370, 589 |
| Cost | $4.31 | $4.28 |

No significance claim from 3 runs per arm. No plugin run ran `occam scan`, so this didn't test the scanner. `docs/evaluation.md` has the reasons and what changed afterward, none of which has run against an agent. Reports, diffs, judge output and traces are in `evals/results/audit-sonnet/`, and the arms are hidden behind `judge/mapping.json`.

## Code size from saved runs (post-hoc, free)

Not preregistered, and added on 2026-11-05 after reading Ponytail's report of 53% less code. No new runs: `evals/code_size.py` reads the saved diffs. Each cell is arm over no skill, as a geometric mean of per-case medians. Source lines are lines added to code files outside tests, and gzip is the size of those lines compressed, which dense code can't game as easily.

| Comparison | All runs with a diff: source lines, gzip, cost | Accepted, finished runs only: source lines, gzip, cost | Cases smaller of those compared |
|---|---|---|---|
| Opus holdout, plugin | 0.72, 0.79, 1.89 | 0.61, 0.65, 1.94 | 3 of 3 |
| Sonnet holdout, plugin | 0.79, 0.86, 1.85 | 0.78, 0.86, 1.89 | 3 of 3 |
| Sonnet Python suite, plugin | 0.92, 0.94, 1.33 (5 cases) | 0.82, 0.87, 1.24 (2 cases) | 4 of 5, then 2 of 2 |
| Opus fresh regression, plugin | 0.92, 0.85, 1.39 | The same | 1 of 1 |
| Opus holdout, compact, against that holdout's no-skill runs | 0.88, 0.89, 0.99 | 0.83, 0.82, 0.96 | 2 of 3, then 3 of 3 |

- **What this shows:** in these runs the plugin delivered less code and cost more. Cost here is a per-case ratio, which weighs cheap cases equally, so it differs from the +57% total in the holdout table.
- **What it doesn't show:** that the code is better. Less can mean less complete, and the accepted-only view leaves few runs on some cases, one plugin run on `pricing-workbook-scale` on Opus. Three runs per arm supports description only.
- **Compact is weak evidence.** Its cost matched no skill, but the skill fired on only one of its three cases (`refund-webhook-consumer`), so the other two compare no-skill runs with each other. That one case went from 125 lines to 82 with compact and 67 with the plugin.
- **Not comparable with Ponytail's figures.** Different tasks, different models and a different measure of delivered lines. Bash was off in its runs and on here.
- **Versions differ.** These runs measured the plugin versions recorded in each section above, so none of them include the principle wording, `occam debt` or `gate`'s scope notes, which came later and have had no agent run.

## Large audit head-to-heads (post-evaluation)

**Second test,** on hash `8cac9607b9697ce0`, `evals/fixtures/blind-audit-large-2`. No measured benefit by the preset rule, and fixed count goes first because the plugin is lower.

| Measure | Plugin | No skill |
|---|---:|---:|
| Critical and high fixed, of 60 (primary, blind judge) | 48, 49, 53 | 58, 57, 57 |
| Located of 122, per run (primary) | 93, 91, 101 | 95, 88, 99 |
| Decoys reported as defects (judge) | 1, 0, 1 | 2, 5, 3 |
| Report claims the diff contradicts (judge) | 0, 1, 2 | 1, 0, 2 |
| Behavior changes not flagged (judge) | 2, 2, 2 | 7, 7, 6 |
| New test functions | 14, 13, 70 | 0, 83, 61 |
| Seconds | 1429, 1193, 1020 | 699, 733, 654 |
| Cost | $13.85 | $17.79 |

**First test,** below.

On hash `d913a354a88b89a1`, Sonnet 5.5, 3 runs per arm, on `evals/fixtures/blind-audit-large`, whose key nobody working on the skill had read. Preregistered, with two primary measures.

| Measure | Plugin | No skill |
|---|---:|---:|
| Located of 122, per run (primary) | 90, 94, 88 | 94, 91, 91 |
| Static of 60 | 38, 41, 39 | 38, 34, 36 |
| Semantic of 62 | 52, 53, 49 | 56, 57, 55 |
| Critical and high fixed, of 60 (primary, blind judge) | 48, 43, 52 | 53, 50, 19 |
| Decoys mentioned, of 43 | 6, 5, 6 | 2, 0, 5 |
| New test functions | 17, 20, 12 | 0, 0, 0 |
| Report claims the diff contradicts (judge) | 1, 4, 0 | 4, 1, 0 |
| Behavior changes not flagged (judge) | 0, 0, 0 | 7, 1, 0 |
| Judge's overall score, of 5 | 4, 3, 4 | 3, 3, 2 |
| Seconds | 742, 803, 939 | 480, 521, 378 |
| Cost | $11.37 | $11.66 |

Tests passed afterward in all six. By the rule fixed in advance this is no measured benefit, since located is lower and decoys are above 1.5 times. `docs/evaluation.md` has what the traces and reports add, including that 11 decoy mentions were correct dismissals of scanner leads.

## Hard cases: round 1 and an exploratory look (post-evaluation)

Fresh cases written blind to the guidance, chosen because they were meant to be hard. Rules and every change are in `PREREGISTRATION.md`.

**Round 1 stopped at its pilot, as its rule requires.** No skill passed 5 of the 8 new cases every time it finished them, leaving 3 cases, under the 4 needed. No plugin run happened, so it says nothing about the plugin. It counts as round 1 of up to 3, at $7.68.

**The look: no sign of a benefit, at more cost.** Exploratory, and not a round. The user chose it after round 1, on the 3 cases no skill had failed, on Sonnet 5.5, 3 runs per arm, $6.10.

| Case | Plugin | No skill |
|---|---:|---:|
| `locker-pickup-reminders` | 0/3 | 0/3 |
| `solar-annual-figure` | 1/3 | 2/3 |
| `water-billing-split` | 2/3 | 2/3 |
| Total | 3/9 | 4/9 |
| Hidden checks passed per run, mean | 93.7% | 96.4% |
| Mean turns | 17.6 | 9.0 |
| Cost | $3.79 | $2.31 (plugin +64%) |

The rule fixed before it ran asked for at least 3 more passes out of 9. These 3 cases are ones the guidance already describes in general terms, so the look was generous, and a one-run difference at this size means nothing either way. A blind audit afterwards rated `locker-pickup-reminders` and `solar-annual-figure` unfair, with checks at fault falling only on plugin runs. Setting aside the one such check that alone failed a run gives 4 of 9 against 4 of 9, which doesn't change the reading.

- **What the plugin got wrong.** A send-back at Stop replaced a good report with a short reply to a note the reader never sees, in all 3 `locker` plugin runs. Two of them then failed a check on the final message, though their first report passed it. The hook also counted a test's expected failure on a copy of the old code as this code's.
- **What send-backs do.** After the fact, in 140 saved plugin runs: 65 were sent back, 74 times, and the agent changed code after 7 of those. The reviewer note accounts for most of what they achieve. One reviewer in the look found a real defect the repo's tests didn't cover. The two runs with a reviewer cost 1.7 and 3 times a no-skill run.
- **Changed afterwards, and not measured.** A send-back now asks for the whole report again, and an unread diff no longer sends an agent back by itself. The skill says to test the old code in its own command, which the hook reads correctly. Counting that failure correctly inside a mixed command was tried and removed, because a fresh review got real failures recorded as passes. Replay on 73 saved runs shows runs sent back falling from 46 to 32, which shows what fires, not that it helps. See `PREREGISTRATION.md`.

## Spend

| Step | Cost |
|---|---:|
| Sandbox probes and live checks | $0.72 |
| Pilots, before any skill existed | $6.47 |
| Trigger suites | $12.75 |
| Smoke, earlier skill-only revision | $12.11 |
| Holdout stopped by the design change, deleted unread | $3.16 |
| End-to-end suites | $7.66 |
| Smoke, plugin | $7.63 |
| Holdout, Opus: plugin and no skill | $13.61 |
| Holdout, Opus: compact | $5.08 |
| Holdout, Sonnet: plugin and no skill | $3.45 |
| Claude-only checks after install | $0.89 |
| **Subtotal, against the $75 cap** | **$73.55** |
| Re-evaluation: fresh case, both arms | $4.10 |
| Re-evaluation: `pricing-workbook-scale` | $3.49 |
| Re-evaluation: `refund-webhook-consumer`, 1 run | $1.25 |
| Re-evaluation: end-to-end preflight on Haiku | $0.09 |
| Fresh-case attempt on an older snapshot, deleted unread | $4.08 |
| Holdout re-runs stopped partway, unused | $2.13 |
| **Total** | **$88.68** |

The user approved up to $15 more for the re-evaluation, about $90 in all. I worked to $88.55 ($73.55 plus $15) and overran that by $0.13. **$6.21 of that $15 produced nothing usable, and those were my mistakes:** a queue I had left waiting on machine load started by itself on an out-of-date snapshot, and I deleted its results unread, which was hasty. I also stopped runs after a session reported hook defects, then again to change their order.

Authoring, review and judging subagents aren't in this total, because the cap covered evaluation runs. Runs labeled `python-` or `audit-sonnet` in the ledger belong to other sessions' separate evaluations and aren't in this total. Neither is later work: hard-case round 1's pilot ($7.68) and the exploratory look ($6.10) came from a separate $25 approval, with $11.22 unspent. The look went $1.10 over the estimate given for it, and its `water-billing-split` case reached $4.45 against a $2 cap, because the runner's cap doesn't stop runs already going. `audit-sonnet` cost $8.58, under a separate $12 approval from the user. `audit-large` cost $23.03, under a separate $25 approval. Writing its fixture used about 1.6 million subagent tokens and judging it 0.4 million, outside that cap. `audit-large-2` cost $31.64 against a separate $30 approval, **$1.64 over it**, because the runner's limit doesn't stop runs in flight. Its fixture used about 1.7 million subagent tokens and judging 0.5 million, outside that cap.


### Where the money went

From `evals/cost_report.py` and the graded runs. Of $79.09 in graded runs, which leaves out the audits because they're scored separately, $53.84 (68%) went to cases no skill passed every time, which can show harm and cost but not a gain. Another $15.11 went to end-to-end checks and pilots, and $10.14 (13%) to cases no skill can fail. Stopped or deleted runs took $9.36 of the ledger's $133.55.

| Comparison, paired by case | Plugin over no skill | Share of the extra: main cache writes | Main cache reads | Main output | Subagents |
|---|---:|---:|---:|---:|---:|
| Holdout, Opus | +61% | 29% | 17% | 13% | 41% |
| Holdout, Sonnet | +85% | 39% | 14% | 24% | 23% |
| Python suite, Sonnet | +28% | 65% | 19% | 16% | 0% |
| Fresh case, Opus | +39% | 37% | 29% | 34% | 0% |

The Opus holdout row counts only runs with a `result` row, which leaves out the two stopped at the time limit, so it differs from the +57% above.

The reviewer costs about $0.21 to $0.26 per reviewed run on Opus and about $0.08 on Sonnet. Where no reviewer runs, most of the extra looks like the plugin's own text sitting in context, not extra turns: in the Python suite the plugin added 1.5 API messages per run, and about 8,000 tokens of context by the last one. That attribution is an estimate from skill file sizes. A held edit is cheap, at most 3.5% of a run on average, even though the held text was already generated.

## Defects the process itself caught

Recorded because each could have produced a false result:

- A "pre-existing failing test" that actually passed, which marked an accurate report as wrong.
- A hidden check that failed a valid `TaskGroup` design, which was the only apparent benefit in early runs. It was removed, and those runs regraded.
- A token metric that undercounted runs continued by the Stop hook, flattering the plugin.
- A broken grader on Unicode in traces, YAML errors that would have stopped language skills loading, and a false positive sending a wording fix to read the performance guide.
- From two independent reviews: a prompt word could waive the destructive git guard, ordinary phrasing could lock an agent out of editing, a `$G` variable hid git from the guard, and exit 2 can fail to block in Claude Code.
- A false positive in the "claimed pass" metric, twice: on a review saying "CI passing tells you nothing", and on a table row marked not run. It's reported as a diagnostic only.
- A holdout blind spot, described above, found only because a judge read the code.
- A grader that left a process running after a hidden check, which used CPU during later runs. It now kills the whole process group.
- A hook parsing bug that hid commands from its own guards, found by reading why one hold fired. See "Re-evaluation after the rewrite fix".

## Not run

| Item | Status | Why |
|---|---|---|
| Codex: discovery, read-only behavior, one fix | **Not run** | Dropped for now at the user's direction, and its login had expired. `evals/codex_smoke.py` is ready. The Codex material is unverified |
| Scenarios s04, s05, s06, s16, s17, s21, s23, s28 | **Not run** | Specified in `scenarios.yaml`. Budget went to the plugin work |
| Skills-only arm on the holdout | **Not run** | Budget. The earlier smoke sweeps cover an earlier skill-only revision |
| Re-evaluation of `invoice-ledger-totals`, more runs of `refund-webhook-consumer`, and no skill on the holdout again | **Not run** | Budget |
| Length-matched placebo arm | **Not run** | Too few runs to detect the effects it looks for |
| Blind human review | **Pending** | Needs a person. See `BLIND_REVIEW.md`. A model judge ran, and doesn't replace it |
| `skills-ref validate` | **Not run** | Auto mode blocked running it from GitHub. Spec rules are checked in `tests/test_package.py`, and two local validators passed |
| Next-developer maintainability | **Not measured** | Out of scope for this suite |

## Threats to validity

- **Ceiling effects.** Almost every case cleared unaided on all three models tried, which limits what the comparison can show in either direction.
- **Small sample.** Three runs per arm on three cases supports description, not inference, and the Sonnet difference is one run.
- **Same model family throughout.** It wrote the holdout, took the tests and reviewed the work. Subagent review isn't statistically independent.
- **Small synthetic repositories.** Published work suggests failures grow with code size, and nothing here is large.
- **Skills fitted to smoke.** Some wording in the skills was written after seeing those fixtures, which is why only the holdout counts.
- **Hidden checks have gaps.** At least one real regression passed them, so a tie on acceptance doesn't show equal quality.
- **Plugin isolated from others.** Eval runs load no other skills or settings, and real sessions have both.
- **Harness differences.** Both arms get a note naming the real git binary, and the Bash sandbox blocks network and loopback.
- **Early rules couldn't separate signal from noise.** At 8 cases and 3 runs each, "fewer on any case" calls harm about 90% of the time with no real effect, and a one-run difference on the holdout is inside noise. The hard-case rounds use a margin from `evals/rule_power.py`. Even so, a real gain of 30 points shows only 62% to 73% of the time at 8 cases, and a gain of 15 points about a quarter of the time, so a flat round is weak evidence of no benefit.
- **The time limit penalized the arm that checks more.** Only skill arms hit 900 seconds, on a machine shared with other work, and a truncated run counts as a failure. Truncation also understates cost: the Opus plugin runs of `pricing-workbook-scale`, 2 of 3 truncated, average $0.91, against $1.16 for 3 complete runs on a later version, so +57% is probably low.
- **Scrutiny wasn't even.** The one check added after the fact came from a plugin failure and lowered only skill arms. A later rules-based battery on `invoice-ledger-totals`, also after the fact and using an input from a plugin run's report, corrupted totals in all 6 no-skill runs and 3 of 3 Sonnet plugin runs, and in none of the 3 Opus plugin runs. Neither is a fair test, and together they show how much the choice of hidden checks decides the score.
- **Every headline describes a different version.** The ledger holds 13 plugin hashes, and the plugin as it stands now has had no full comparison.
- **Runs are unattended and one-shot.** A hold that asks a person becomes a denial, nobody answers questions, and there's no follow-up message. Real sessions have all three.
- **Pass or fail reads the code, not the report.** A failure the agent admits and one it hides score the same, though the first costs a person far less. A blind model judge tried this on the 28 failing Python suite runs, 14 per arm, after the fact. It came out even: 6 disclosed in each arm, 4 silent with the plugin against 5 without, 1 partly with the plugin, and 3 per arm it couldn't judge because a check's name didn't say what failed. That was a test of the rubric, and it's a noisy one: given the full text of 5 cut-off reports, a second judge changed 3 labels.
- **The plugin is tested whole.** Apart from compact, no arm removes one part, so nothing here shows which part earns its cost.
