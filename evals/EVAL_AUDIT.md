# Audit of occam's evaluation suite

Written 2026-11-06. The question: do these tests measure what the owner wants to know?

**Short answer: mostly not.** The suite is honest and carefully run, and its negative results are probably right about what they measure. But what it measures is narrow: whether Sonnet finds and repairs planted security and business-rule bugs in Python services of about 28,000 lines, and whether small tasks pass hidden tests that no-skill agents nearly always pass anyway. Most of the owner's list has no agent-level outcome test, and the two primary audit measures have construct problems serious enough that neither should stay primary.

## Scope and method

- **Read:** the files named in the brief, the hidden check names of every non-hard case, a sample of prompts and check bodies, and the three audit keys. All 18 saved audit reports, verdicts and diffs went through my scripts, and I read samples of them directly, not all of them end to end.
- **Not assessed: `evals/cases/hard/`.** I did not read it, or `evals/results/hard-*`, or `evals/FROZEN.sha256`. I read only its `scenarios.yaml` entries and the preregistration's account of round 1. Nothing below judges those cases.
- **Run:** free local analysis only. No model calls and no writes inside the repository. Agent diffs were executed only under `sandbox-exec` on scratch copies. Scripts are in `evals/results/eval-audit/scripts/`.
- **The tree moved while I read it.** `docs/evaluation.md`, `docs/evidence.md`, `evals/RESULTS.md`, `evals/README.md` and `evals/PREREGISTRATION.md` all changed. `docs/evaluation.md` now has a section, "What these tests can't show", conceding some of what I found independently. I reproduced its numbers. Those are documentation edits: `evals/score_audit.py` is unchanged since Nov 5, and it and the prompt in `evals/audit_comparison.py` still behave as described here. I cite sections rather than line numbers for files still moving.
- **Abbreviations:** L1 is `audit-large` (`evals/fixtures/blind-audit-large`), L2 is `audit-large-2`, S is `audit-sonnet` (`evals/fixtures/blind-audit`). "Serious" means critical or high.

### What the suite gets right

So the rest is read fairly: preregistration with negative results first, intent-to-treat scoring, hidden checks agents can't see, calibration where the starter fails, the reference passes and each trap fails (`tests/test_calibration.py`), sandboxed grading, a real cost ledger, `evals/rule_power.py`'s selection-aware margins, and the pilot rule that stopped round 1 rather than running a test that couldn't show a benefit. Two things I suspected turned out not to be problems today: see "Located" in section 2.

## The eight findings that matter

1. **Most of the owner's list has no outcome test.** Of 33 rows in section 1, 7 have an outcome measure with a comparison arm and room to move. 12 have one that is at the ceiling, a proxy, or a single case. 3 are process only. 11 have little or nothing beyond rule or tool tests.
2. **The audit tests can't see most of what the owner named.** All 60 judged defects per large fixture are security, business-rule or reliability bugs. By my keyword search of the keys' `kind` and `what` fields, L1 and L2 contain no planted overengineering, third-party reinvention, comment, naming or base-class defect. Duplication appears only as 8 low-severity unused copies and 1 medium near-copy on L1, and not at all on L2. None of that is serious, so "fixed" cannot register it.
3. **"Located" is mostly citation-format noise around a ceiling.** Parsing line ranges and lists correctly adds 1 to 13 per run and flips the sign of the arm difference in both large fixtures. Whole defects score 0 of 6 by proximity while the judge says all 6 runs reported them. Run-level correlation with fixed is about zero (-0.04, -0.03, +0.15).
4. **"Fixed" rewards changing more, and the prompt, README and key disagree about what's correct.** It correlates with files changed (r = 0.73, 0.88, 0.85) and with new damage (0.38, 0.59, 0.98). On L2 it runs opposite to the same judge's overall score (r = -0.65), and the run that fixed most was ranked last.
5. **The verdict depends on a weight nobody has set.** Fixed minus w times (new damage + unflagged changes): at w = 0 no skill leads on median in all three fixtures. At w = 2 the plugin leads on mean in all three (+4.0, +13.7, +7.3). The "no benefit" and "real benefit" readings differ only by that weight.
6. **The fixture is the independent unit, and there are two.** With a real fixture-to-fixture spread in the plugin's effect of 5% of scale and no true average effect, 12 runs per cell on 2 fixtures reads as significant 46% of the time (simulated). More runs on the same repositories make this worse, not better.
7. **Nothing tests asking.** `AskUserQuestion` is in none of the 29 non-hard case allowlists or the audit prompt's, the audit prompt says nobody is available, no case has a responder, and s23 and s51 never ran. A stated requirement of the brief is unmeasured.
8. **"Large" isn't large.** L1 and L2 have 14,053 and 15,433 source lines plus about 12,000 test lines, and plugin reports say readers read every line, at $3 to $7 a run. Nothing tests the tools' stated purpose, code too large to read. The largest agent test is under 30,000 lines.

---

## 1. Coverage

"Run only": specified scenarios (s04, s05, s06, s16, s17, s21, s23, s28, s50 to s54, s61) get no credit. s70 to s77 are not assessed. Case names are under `evals/cases/`. "Ceiling" means no skill passed every run, so a gain can't appear. "Floor" means both arms fail.

| # | Owner's item | What actually measures it | Measured as | Can it show a gain? Notes |
|---|---|---|---|---|
| 1 | Overengineering | Rules `single-impl-abstraction`, `pass-through` (`tests/test_scanner_rules.py`); `evals/code_size.py`, post hoc; one model's Simplicity score on 27 Opus runs (RESULTS "Blind model review"); `trivial-fix::test_no_design_documents_or_stray_files` | Static rule; outcome only as a weak proxy | 0 planted in L1, L2; 1 low-severity in S (D72), outside the judged set. s25 tests the opposite failure. Smaller isn't simpler |
| 2 | Duplication | Clone rules; `export-format` rounding checks (s03: don't merge wrongly); 5 entries in S, 9 in L1 (8 are low-severity unused copies), 0 in L2, none serious | Static rule; located only | s52 not run. Never reaches the fixed count |
| 3 | Overly complex algorithms | `bench` tests; scale checks in `dedupe-at-scale`, `async-fetcher`, `pricing-workbook-scale`, `runsheet-scale` | Outcome for "too slow"; nothing for "needlessly complex" | All ceiling |
| 4 | Third-party first | `reuse`, `deps`, `tools` tests (`tests/test_tools.py`, `tests/test_scale_tools.py`) | Static only. Nothing in agent runs | s04, s05, s06, s53 not run. The eval's Bash sandbox blocks network (RESULTS threats), so it can't be tested as built |
| 5 | Bloat | `changed_lines`, lines added, `code_size.py`; stray-file checks in `trivial-fix` and `freight-lane-quotes`; 8 low-severity dead-code entries in L1 | Outcome proxy (size), post hoc | Plugin 1,118 lines added against 4,070. Prereg says volume is "never a success metric", and fewer lines came with fewer fixes |
| 6 | Non-scalable architecture | Scale checks as row 3; N+1 and unbounded-load entries (13 in L1, 18 in L2, none serious); rule tests | Outcome at function scale; nothing at architecture scale | Ceiling; located only in audits |
| 7 | Not properly tested | `tool-rental-late-fees::test_suite_catches_the_bug` (s45, a good check); `dirty-tree::test_existing_tests_not_weakened`; new-test counts, post hoc | Outcome on one case; a count otherwise | 3/3 against 1/1, 2 no-skill runs not run. Quality of tests agents wrote in audits is unmeasured |
| 8 | Self-critique | e2e `high-consequence-review::test_reviewer_agent_ran`; fallback runs; judge's false-claim count | Process; one weak outcome | False claims tie, 8 against 8 on L1 and L2. In S a reviewer ran and a false claim still shipped. Coverage map: "not separately run" |
| 9 | Security | s09 `tenant-invoice-export`, s24 `review-with-injection`, s47 `partner-meter-backfill`; about 32 of 60 judged defects in each of L1, L2 | Outcome | Best covered. Hidden attack tests are at ceiling; audit fixes are read by a judge and no exploit is run |
| 10 | Usability | Rules `a11y-missing`, `opaque-error`; `test_bad_input_is_a_client_error` incidentally | Static rule | Nothing on product usability. Human packet (`evals/BLIND_REVIEW.md`) pending |
| 11 | Comments, too many or too few | s44 `harbour-tide-gauges::test_no_narrating_comments`, `test_no_history_in_comments`, docstring checks; rules | Outcome on one case, by regex | "Too few" only as "a docstring exists" |
| 12 | Reusing existing code | s02 `export-format::test_reference_is_the_link_slug` checks behavior matches the helper; `reuse` tool tests | Outcome proxy | Ceiling. Scenario calls reuse "a design diagnostic", and no such grader exists in that case. s52, s53 not run |
| 13 | Shared code, base classes | s08 in `sync-adapter-bug` (ceiling); rules `pull-up-method`, `base-class-bypassed` | Static rule; one ceiling outcome | 0 planted |
| 14 | Other agents | s15 `dirty-tree-failing-suite` (Sam's uncommitted lines); `coord`, `fix` refusals (`tests/test_tools.py`, `tests/test_review_regressions.py`) | Outcome on a static stand-in; static otherwise | Ceiling. No run has ever had a second live agent |
| 15 | Language best practices | Python: s40 to s47. JS s24, SQL s26. TS e2e `language-skill-typescript`. Go, Rust `tests/test_language_claims.py` | Outcome for Python; process or static elsewhere | Python tied 7/18 each, with references read in 1 of 21 and 1 of 15 runs, so the guidance itself is barely tested |
| 16 | Checking performance, expected behavior | `check_after_last_edit` (12/14 to 14/14); `bench` tests; s11 to s13; `test_behavior_preserved` | Process, plus outcome at ceiling | The metric only sees Edit, Write and NotebookEdit (`grade_workspaces.py:162`), so it's blind to the `python3 - <<E` edits audit runs used |
| 17 | Sticking to the plan | `goal` tests (`tests/test_tools.py`) | Static only | s21 not run |
| 18 | Incomplete implementation | s20 `export-format` (ceiling); s42 `grain-elevator-settlement::test_old_module_really_was_broken_up` (floor, 0/3 each); `unfinished.py` replays count firings only | Outcome | One ceiling, one floor. A floor can move up, but neither arm has |
| 19 | Working toward a goal | `goal` tests | Static only | Nothing in agent runs |
| 20 | Number of subagents | `subagents` count; Agent calls in traces (L1 3-4 against 5-10; L2 4-8 against 8-10); `map`, `partition` tests | Process | Nothing links count to outcome. s16, s17 not run. The reader-budget change is confounded with the fixture change |
| 21 | Architecture down to hardware | Rule tags; `dedupe-at-scale::test_full_size_within_memory` | Static rule; one ceiling outcome | Reports may say hardware wasn't examined, and nothing scores that |
| 22 | Non-standard naming | s44 `test_names_follow_the_vocabulary`, `test_no_history_in_names`; rules | Outcome on one case | Tests repo vocabulary, not industry terms. One such check was called debatable and flips a run |
| 23 | Correcting what it sees | L1, L2, S fixed against reported; judge's `over_cautious`; s22 diagnostic | Outcome, by judge | Has room. It's where the plugin lags: 22 left open against 4 on L2 |
| 24 | Asking questions, permission | `ended_with_question` regex (4 hits across all saved graded non-hard runs; the audits aren't graded this way); e2e `destructive-git-guard` (hook denial); judge's `authorization` lists, post hoc | Process; proxy | See finding 7 |
| 25 | Audit: cell | Rule tests for `.ipynb` and `scan --stdin`. s46 is a repair, not an audit | Static rule | Nothing with an agent |
| 26 | Audit: file | No single-file audit. Nearest is s40 `freight-lane-quotes`, 1,053 Python lines, scored by regex on the final message | Outcome, small package | 1/3 against 0/3, rerun 1/3 |
| 27 | Audit: small repo | S, 3,064 lines, 83 planted | Outcome: proximity plus post-hoc judge | Key read by author. s50 not run |
| 28 | Audit: medium repo | L1 and L2. The repo calls these "large" | Outcome: proximity plus one judge | Three runs per arm, two fixtures |
| 29 | Audit: large repo | None. s54 not run, and as specified it's transcript-only, so process. One uncontrolled agent on a real 33,021-line repo; scanner on 15 real repos | Static rule and tool | No comparison exists |
| 30 | Audit: very large repo | Scanner speed and memory, up to 10 million generated lines (`tests/test_scale.py`, `tests/test_scale_tools.py`) | Tool speed only | Nothing about whether findings are good. Nothing with an agent |
| 31 | Repair | L1, L2, S judged fixed; s07, s08, s45 hidden checks | Outcome, read and not executed | Fixture tests pass with all defects in place, so they can't confirm a repair |
| 32 | Generating new code | Features added to existing repos in smoke, holdout, python (46 to 2,160 Python lines, plus s43 at 23,717 generated) | Outcome, behavior only, at ceiling | No generation from an empty repo. Maintainability "not measured" (RESULTS "Not run") |
| 33 | Codex | `evals/codex_smoke.py` not run; `results/codex-auth-check` has one record, return code 1. `tests/test_hook_scan.py`, `tests/test_package.py` | Static only | No Codex behavior observed |

**Tally.** Real outcome, comparison arm, room to move: 7 (rows 9, 15, 18, 23, 27, 28, 31). Ceiling, proxy or one case: 12 (3, 5, 6, 7, 11, 12, 13, 14, 16, 22, 26, 32). Process: 3 (8, 20, 24). Static only or nothing: 11 (1, 2, 4, 10, 17, 19, 21, 25, 29, 30, 33).

**`docs/coverage-map.md` is both over- and under-crediting.** Of its 94 rows, by my parse, 37 cite a scenario that ran, 25 are lint only, 9 are "guidance only", 13 cite only specified scenarios (7 with nothing else, 6 with lint), 4 are e2e or trigger only, 4 are model-judge or fallback runs, and 2 cite only hard scenarios. "Audit existing code at any size" lists s50, s51, s54, none of which ran, while the audits that did run have no scenario ID at all, and `evals/audit_comparison.py` isn't linked from `scenarios.yaml`. The map also doesn't say which rows are outcome and which are process.

---

## 2. Construct validity

| Measure | What it really measures | Main way it misleads | More writing? | More citing? | More changing? |
|---|---|---|---|---|---|
| Acceptance pass rate | All hidden checks pass | Ceiling, all-or-nothing, check gaps | Only regex checks | No | Rarely penalized |
| Located, within 3 lines | A `path:line` string near the key's line | Format noise, not detection | Yes | Yes | No |
| Judge's fixed count | One model's read of a diff against the key | Rewards volume and unilateral change | A little | No | **Yes** |
| Decoys, proximity | Any mention within 1 line | Punishes correct dismissals | Yes, wrongly | Yes, wrongly | No |
| Decoys, judge | Reported as a defect, in that judge's view | One fixture only, questionable key entries | No | No | Slightly |
| Hidden checks | Behavior at inputs the agent can't see | What the author thought of | Some | No | Partly |
| Tests pass after | The agent's own edited tests pass | 18 of 18, no signal | No | No | No |
| New tests, lines added | Volume | Not quality | Yes, tests | No | Yes |
| Judge's damage, false claims, unflagged | Unweighted list lengths | Severity ignored | Partly | No | Damage rises |
| Judge's rank and overall | Holistic preference | Arm can be inferred | Partly | No | No |
| Skill fired, e2e, triggers | The mechanism ran | Says nothing about the code | No | No | No |
| Cost and time | Cost and time | Cross-test cache settings, shared machine | No | No | Yes |

### Acceptance pass rate, and the ceiling issue

**The known issue checks out, and it understates the problem.** I tabulated all 20 non-hard cases with a no-skill arm from `graded.json`, using the corrected `tool-hire-overdue-report`:

| No-skill pass rate | Cases | Which |
|---|---:|---|
| 100%, only harm can show | 16 | 8 smoke, 3 holdout, `runsheet-scale`, s41, s43, s45, s47 |
| 0%, floor | 3 | s40, s42, s46 |
| Between | 1 | s44 at 1/3 |

Every non-tie on a ceiling case was a loss, because a gain is arithmetically impossible there. `RESULTS.md` says $53.84 of $79.09 in graded runs (68%) went to such cases. Four things beyond the known issue:

- **Harm detection is weak too.** 8/9 against 9/9 is one-sided Fisher p = 0.5, yet "Regressions to report first" leads `RESULTS.md`. The prereg's own amendment says such rules mostly fire on noise.
- **The ceiling is partly weak checks, not easy work.** On `pricing-workbook-scale`, silent regressions passed all 14 checks until one was added afterward. On `invoice-ledger-totals`, a later battery corrupted totals in all 6 no-skill and 3 of 3 Sonnet plugin runs, all of which had passed (RESULTS "Scrutiny wasn't even").
- **All-or-nothing is brittle.** One unfair check moved s41 from 3/3 to 0/3 in both arms. Fraction of checks passed is more sensitive in principle, but I computed it free on the Python suite and it's a tie: 0.879 against 0.877.
- **The audit measures hit the same ceiling.** The judge has serious defects "not missed" in 352 of 360 and 356 of 360 run-defect pairs on L1 and L2, and 248 of 252 on S. Critical located is 17 to 20 of 20. L2 no-skill fixed is 57.33 of 60, so its headroom is 2.67, or 4.4% of scale. **A 5% gain over no skill on L2 is impossible: 57.33 × 1.05 = 60.2 > 60.** The prereg's first lesson was repeated in the test built to escape it.

### Located by proximity

**What it is.** `evals/score_audit.py:40` takes the first number after `path:`, and `:43` asks whether it's within 3 lines of the key.

- **Agreement with the judge, serious defects, L1 and L2, 720 run-defect pairs.** The judge says 708 were reported or better. Proximity gives 628. Of the 12 the judge calls missed, proximity credits none. So it gives **no false credit, but misses 11%** (31% on S, where the post-edit line flaw also applies). Variation in located on serious defects is mostly scoring error around a true rate near 98%.
- **Citing a function's start loses credit.** `inventory-05`, `patients-05` and `scheduling-06` score 0 of 6 by proximity and 6 of 6 by judge. `core-01` and `returns-01`, both critical, score 1 of 6 and 6 of 6. Example: all six L2 reports name `vetdesk/records/api.py:153` for `records-05`, the `def` line, and the key's line is 159.
- **Citation style drives the score.** Ranges and lists count only their first number. L2 reports used from 2 to 113 ranges. Handling ranges and lists up to 30 lines changes located by +1 to +13 per run, and flips the arm difference: L1 from -1.33 to +1.00, L2 from +1.00 to -1.33. **The rule's noise is larger than the effect it's reading.**
- **It doesn't predict repair.** Correlation with fixed is -0.04, -0.03 and +0.15.
- **All severities count the same.** A low-severity dead-code find equals a tenant leak, and the headroom is in medium and low (no-skill low: about 7 to 9 of 21).

**Gaming.** Citing more works by construction, with no precision penalty. Synthetic reports, scored on L1 with the real logic:

| Report, no reading done | Citations | Located | Decoys |
|---|---:|---:|---:|
| Every 7th line of every file | 3,852 | 122/122 | 18/43 |
| Every line matching a risky-pattern grep | 3,819 | 91/122 | 32/43 |
| Real runs, no-skill mean | 177 | 92/122 | 2 to 3 |

`tests/test_audit_comparison.py` asserts a citing-everything report shows in the decoy count. True at that extreme, but the only rule is a 1.5-times ratio between arms, not a cap or a precision floor.

**Two suspicions I tested.** `item["file"].endswith(path)` can match the wrong file, since L2 has 9 files called `repository.py`. For located it barely matters: requiring a unique path changed the count by at most 3 per run, because agents mostly cite full paths. For decoys it does matter, because those counts are small (next subsection). And citation volume isn't inflating scores now: citations against located is r = 0.35 and -0.06 on L1 and L2, though 0.80 on S.

### The blind judge's fixed count

- **Three authorities conflict over what's correct.** The prompt says fix "without changing public behavior or the data model" (`audit_comparison.py:44`). L2's README says "Where code and a rule disagree, the rule wins." The key flags some defects `needs_decision`. The score uses none of these to decide what counts.
- **`needs_decision` is undefined and inconsistent, and the concurrent doc edit reads too much into it.** `docs/evaluation.md` now says no-skill runs fixed 18 "which a person was meant to decide". But 17 of those 18 L2 entries cite a numbered rule the README says wins, against 3 of 9 on L1. So "half the L2 gap is on decision items" is arithmetically right (54/54 against 43/54, and 118/126 against 107/126), and it can't tell you who was right. Across all 18 runs: decision items 92 against 74 of 117 favoring no skill, other items 303 against 308 of 369 favoring the plugin, the latter including the 19 run.
- **It rewards volume.** Files changed against fixed: r = 0.73, 0.88, 0.85. Against new damage: 0.38, 0.59, 0.98. L2's judge ranked the 58-fixed run last of six and two 48-to-53 runs first, saying "Ranking favours attempts that say true things and leave code no worse over raw fixed counts". The primary measure and the judge's own conclusion disagree.
- **It's bimodal.** The 19-fixed run labels most serious findings "OPEN (behaviour change)", following the prompt's literal wording. The judge called this over-cautious. That one run sets SD at 9.8 or 2.9. See section 4.
- **The headline tie was a coincidence.** 293 against 294 of 360 hid medians of 48.5 and 55. `RESULTS.md` now says so. With the 19 run, the 95% interval on the mean difference is -13.2 to +12.8 of 60, which isn't "about the same", it's "unknown". Without it, -9.8 to -1.4. Stratified rank test, post hoc: p = 0.14 on L1 and L2, 0.015 adding S.
- **Nobody knows its reliability.** One judge per fixture, so judge and fixture are fully confounded. It ran nothing. Its standards were set while reading ("Standards applied to every attempt", in its notes). No rubric or prompt is stored: `evals/` has no judge script, only verdict files. No test-retest exists. On a related rubric, a second judge changed 3 of 5 labels (RESULTS threats).
- **The blinding leaks.** All 6 plugin reports on L1 and L2 use "scan" and "leads", and 0 of 6 no-skill reports use "scanner". One opens "`[tool] scan` produced 304 leads". The judge can sort arms even with the name removed. Its top two ranks on L2 were plugin runs. I also note letter C ranked last in all three tests, a 1-in-36 event under random labeling for any one letter. That's suggestive at most, but randomizing is free.
- **One validation in its favor.** The original-suite run below independently confirms a damage item it found by reading (labels returning 500 in L1 `with-2`).

### Decoys

- **Proximity punishes showing your work.** L2 `with-0` writes "`pharmacy/service.py:101,389` are safe: allowlisted columns", and line 101 scores as a decoy flagged. `docs/evaluation.md` found 11 of 18 plugin mentions on L1 were correct dismissals. A report that silently skips decoys scores better than one that checks and dismisses them.
- **Short paths produce false hits.** L2 `without-2` scores 3 decoys. Two are collisions: `repository.py:198` in a sentence about `claims/repository.py` and `repository.py:164` about messaging both match decoys in `scheduling/repository.py`.
- **It has no relation to the judge's count.** Across the six L2 runs, proximity (3,1,1,2,1,3) against judge (1,0,1,2,5,3): r = 0.00. By the judge, the plugin is better (2 against 10). By proximity, level (5 against 6).
- **Key quality is questionable.** `core/auth.py:74` was raised by 4 of 6 runs, and the judge notes 1,000 against 200,000 iterations "is a real timing difference".
- **Decoys aren't precision.** Each large-fixture report has 49 to 123 distinct citations near neither a defect nor a decoy. Some restate a keyed defect at another line and some are real unkeyed defects (section 3). Nobody has scored the rest, so report precision is unknown.

### Hidden checks

Valid as written and well calibrated, and calibration only proves a check catches what its author imagined. Beyond the gaps above:

- **Regex on final messages is loose.** `dirty-tree::test_report_surfaces_the_skipped_database_tests` passes on the word "database" or "integration". `freight-lane-quotes`'s `HOW_CONFIRMED` passes on `\bread\b`, `output` or `->`. `freight-lane-quotes` does cap padding with `MAX_WORDS`, which is good; most others have no cap.
- **Some acceptance checks are process.** `shipping-fx-rates::test_read_a_targeted_fraction_of_the_tree` counts the main agent's Reads and tool output, so reading through a subagent isn't seen.
- **Scrutiny is uneven.** The check added after the fact lowered only skill arms (acknowledged in `RESULTS.md`).

### Tests pass after

18 of 18, which can't discriminate, and the fixtures pass with every defect in place. It also runs **the agent's edited tests** (`_tests_pass`, `audit_comparison.py:115`). "Tests passed afterward in all six" conceals edits. I restored the original tests over each run's final source and ran them in a sandbox:

| Original tests failing | Plugin runs | No-skill runs |
|---|---|---|
| L1, of 1,496 | 0, 0, 2 | 1, 0, 0 |
| L2, of 1,942 | 0, 0, 0 | 10, 129, 1 |

**Don't read these as damage counts.** Of the 129, 113 share one message, "owner N not found", from a new owner check the old test setup doesn't satisfy. Some tests pin defects, so a failure may mean a correct fix. Triaged by root cause, though, this is a free, objective signal of pinned behavior changed that nobody is collecting.

### The others

- **New tests, lines added.** Volume. Plugin runs added tests in 6 of 6 large runs and no-skill in 2 of 6, a real behavior difference, but no mutation score says whether those tests catch anything. Lines added confounds with fixes.
- **Damage, false claims, unflagged changes.** Useful and unweighted, with "low" items counting like serious ones. Unflagged changes do separate the arms (stratified p = 0.02 on L1 and L2, one of 11 post-hoc tests). False claims don't (8 against 8), and that's the most direct outcome of self-critique.
- **Skill fired.** `grade_workspaces.py:166` matches only the name `occam`, so `occam-audit` loads don't count and `freight-lane-quotes` shows 0/3 in the plugin arm.
- **Mechanism checks.** Traces omit hook context and Stop feedback (`docs/evaluation.md`, "Enforcement can't be confirmed"), so even the process evidence is incomplete.
- **Time.** The cleanest separation in the data: about 1.8 times as long, stratified p = 0.005. Machine load wasn't controlled.
- **Scanner on real repositories.** 31% worth acting on, 57% true but minor, 12% false, of 103 leads. Tool behavior, judged by one model, not an agent outcome.

---

## 3. Fixtures and tasks

**Model-written, model-solved, model-judged.** Every fixture, agent and judge is one family, and no person has reviewed anything (`evals/BLIND_REVIEW.md` is still pending). The concern isn't abstract: a defect a Claude writer thinks to plant is one a Claude reader recognizes. Serious-defect recall of 98% on fixtures sits badly beside the only real-repository agent run, which reported 5 main findings in 76 seconds, never mentioned 27 `float-money` leads in a billing app, and left billing logic unread (`docs/evaluation.md`, "One agent on a real repository"). That run had no comparison and no hooks, so it's a warning and not a measurement.

**Planted defects don't look like real ones.**

- **They're local and spec-backed.** Each has one file, one line and one snippet. L1's README has 74 numbered rules and L2's has 103. 79 of 122 L2 entries (18 of 20 critical) and 39 of 122 L1 entries cite a rule or the README. Real AI-generated repositories rarely ship a 103-rule contract saying the rule wins. With one, an audit becomes a checklist comparison, which is likely part of why recall is so high. It also changed sharply between the two fixtures, so they aren't replicates.
- **They're mostly the wrong kind.** My keyword pass on `kind` (rough, and spot-checked) puts about 32 of 60 serious defects in each large fixture in security or tenancy, and about 21 to 22 in business rules. The owner's maintainability concerns are nearly absent, and real AI-code failure modes (duplicated logic, needless layers, drift) are structural, not one-line.
- **They're dense and evenly spread.** About 8 per thousand source lines, about 10 to 14 per package, written package by package. That matches a read-by-package audit strategy suspiciously well.
- **The key is incomplete.** Leaving out clusters within 25 lines of a keyed defect, 9 off-key clusters on L1 and 17 on L2 are still cited by at least 4 of 6 runs. I confirmed two in the code: L2 `records/api.py:255` returns `"total": len(rows)` against rule 98 (6 of 6 runs), and L1 `invoicing/ledger.py:7` caps each query at 200 rows, which 5 of 6 reports flag. Finding or fixing these earns nothing, and fixing them can count against a run as an unflagged change. Others may restate a keyed defect from another location, or be false; I didn't check them all.

**Nobody can answer, though asking is required.** The audit prompt says "Nobody is available to answer questions during this run". `RESULTS.md` says holds become denials and there's no follow-up message. Listing decisions in a report is a different skill from asking well, and with no hidden preference in any fixture, asking couldn't earn anything even if a responder existed. This is the largest single mismatch with the brief.

**Greenfield against repair.** No case starts from an empty repository. "New code" means a feature in an existing small repository, judged by behavior, so a sprawling correct solution passes. The owner's concerns about generated code (overengineering, duplication, bloat, naming, comments, shared code) only matter later, when someone changes it, and "Next-developer maintainability" is listed in `RESULTS.md` as "Not measured". No test has that follow-on step.

**Repository sizes.**

| Size | Agent tests |
|---|---|
| Under 500 lines | 12 cases |
| 500 to 3,000 | 6 cases, plus S (`bikeshare-dock-usage` is one notebook, not counted here) |
| About 24,000 to 28,000 | L1, L2, s43 |
| Above 30,000 | None with a comparison |

Plugin reports say every line was read ("Five read-only readers read every line" on L2, "every line" on L1). The prereg called L1 "a repository too large to read whole", and it wasn't. So `map`, `partition`, `baseline` and `ledger` haven't faced their intended condition. Measuring the scanner at 1.5 million lines shows speed, not audit quality.

**Narrow in other ways.** All audit runs use one prompt, one model (Sonnet 5.5), and Python with the standard library and SQLite: no framework, no real dependencies, one JS file. Third-party decisions can't arise. TypeScript, Go and Rust, large parts of real AI-written code, have no audit test.

**Hard to make harder.** The prereg records that fresh authors asked for cases a strong agent fails mostly didn't manage it: no skill passed 5 of 8. That's a finding about the method. Model-authored small cases may simply not reach this model's failure modes.

---

## 4. Statistical power

### Per-run data

| | L1 plugin | L1 no skill | L2 plugin | L2 no skill |
|---|---|---|---|---|
| Located of 122 | 90, 94, 88 | 94, 91, 91 | 93, 91, 101 | 95, 88, 99 |
| Mean, SD | 90.67, 3.06 | 92.00, 1.73 | 95.00, 5.29 | 94.00, 5.57 |
| Fixed of 60 | 48, 43, 52 | 53, 50, 19 | 48, 49, 53 | 58, 57, 57 |
| Mean, SD | 47.67, 4.51 | 40.67, 18.82 | 50.00, 2.65 | 57.33, 0.58 |

### Run-to-run spread

Pooled within cells, 12 runs less 4 cell means gives 8 df.

- **Located:** (9.33 + 3 + 28 + 31) / 4 = 17.83, so **SD 4.22**. As a check, the variance implied if defects were independent (from each defect's hit rate across 6 runs, corrected) gives SD about 3.0. So 3.0 to 4.2.
- **Fixed, all runs:** (20.33 + 354.33 + 7 + 0.33) / 4 = 95.5, so **SD 9.77**.
- **Fixed, without the 19:** (40.67 + 4.5 + 14 + 0.67) / 7 = 8.55, so **SD 2.92**.

Two warnings. Fixed is overdispersed: within-arm variance is 2 to 6 times what independent defects imply, consistent with each run having a disposition about how much to change, which again suggests willingness as much as ability. And variance isn't constant: near the ceiling, L2 no skill has SD 0.58. A pooled SD is an approximation.

### Fixture-to-fixture spread

- **Fixture means:** located 91.33 and 94.50, 2.6% of scale. Fixed 44.17 and 53.67, or 49.2 and 53.67 without the 19. That's 7% to 16% of scale, confounded with judge and with rule density.
- **What matters for inference is how the arm effect varies by fixture.** Located: -1.33, +1.00. Fixed: +7.00, -7.33, or -3.83, -7.33 without the 19. As percent of scale with S: fixed -9.5, +11.7, -12.2, or -9.5, -6.4, -12.2 without the 19.
- **Estimated spread of the true effect, σ_δ:** variance of the two effects minus what noise would produce. Located: 2.72 - 11.89 is negative, so 0. Fixed: 102.72 - 63.67 = 39, so 6.2, or about 0 without the 19. **With 2 fixtures this has 1 df, and its 95% interval on an SD runs from ×0.45 to ×31.9. It's not an estimate.** So below I use assumed values of 0, 2% and 5% of scale, and these are assumptions.

### Runs per arm, one fixture

To detect a difference δ at two-sided α = 0.05 with 80% power: n per arm = 2(1.960 + 0.842)²σ²/δ² = 15.7σ²/δ², then raised using t on 2n-2 df.

"5% of the score" can mean of the current mean (located 93, fixed 49) or of the maximum (122, 60), so both are shown. Worked example: 15.7 × 17.83 / 4.65² = 12.9, and 14 after t.

| Spread assumption | 5% of mean | 10% of mean | 5% of max | 10% of max |
|---|---:|---:|---:|---:|
| Located, δ | 4.65 | 9.3 | 6.1 | 12.2 |
| SD 3.0, independent-defect | 8 | 3 | 5 | 2 |
| **SD 4.22, pooled** | **14** | **5** | **9** | **3** |
| SD 8.1, upper end of SD's interval | 49 | 13 | 29 | 8 |
| Fixed, δ | 2.45 | 4.9 | 3 | 6 |
| **SD 2.92, without the 19** | **24** | **7** | **16** | **5** |
| SD 5.6, upper end of that interval | 84 | 22 | 56 | 15 |
| **SD 9.77, with the 19, means** | **251** | **64** | **168** | **43** |

**These numbers say only whether the plugin differs on those fixtures. They don't generalize.** Also, a 5% gain on L2 fixed is impossible at the current ceiling, whatever n is.

### Adding fixtures

With k fixtures and n runs per cell, the variance of the mean difference is 2σ²/(kn) + σ_δ²/k, and the multiplier is t(k-1) when generalizing. For example, k = 8, n = 3, fixed without the 19, σ_δ = 3: SE = √(2 × 8.55/24 + 9/8) = 1.36, and MDE = (2.365 + 0.896) × 1.36 = 4.4.

The smallest detectable difference, as % of the maximum, with σ_δ = 0 / 2% / 5% of scale. Cost is at $5 per run, for two arms.

| Fixtures × runs per cell | Per arm | Cost | Located | Fixed, no stopper | Fixed, with stopper, means |
|---|---:|---:|---|---|---|
| 2 × 3, today | 6 | $60 | 6 / 34 / 57 | 9 / 44 / 64 | 29 / 134 / 141 |
| 2 × 12 | 24 | $240 | 3 / 24 / 52 | 4 / 28 / 54 | 13 / 69 / 83 |
| 4 × 3 | 12 | $120 | 4 / 7 / 12 | 6 / 9 / 13 | 19 / 28 / 30 |
| 4 × 6 | 24 | $240 | 3 / 6 / 11 | 4 / 7 / 12 | 13 / 20 / 22 |
| 6 × 4 | 24 | $240 | 3 / 5 / 8 | 4 / 6 / 9 | 13 / 17 / 18 |
| **8 × 3** | **24** | **$240** | **3 / 4 / 7** | **4 / 5 / 7** | **13 / 16 / 16** |
| 12 × 3 | 36 | $360 | 2 / 3 / 5 | 3 / 4 / 6 | 11 / 12 / 13 |
| 16 × 3 | 48 | $480 | 2 / 3 / 4 | 3 / 3 / 5 | 9 / 10 / 11 |

**At the same cost, more fixtures wins decisively.** Simulation (`sim.py`) on the fixed model confirms it and shows the failure mode: with no true average effect and σ_δ = 5% of scale, a pooled test reads significant 20% of the time at 2 × 3, 32% at 2 × 6, and **46% at 2 × 12**. Treating the fixture as the unit holds it at 5%. Another 30 runs on L1 and L2 would give a confident answer about those two repositories and little else.

**Means are the wrong statistic here.** With a stopper mode at 1 in 12 in both arms, 8 × 3, true effect +6: mean test power 0.51, within-fixture rank test 1.00. At +3: 0.21 and 0.73.

### Where 6 or 12 per arm makes the estimate itself unreliable

| Thing being estimated | At 6 per arm (2 × 3) | At 12 per arm (4 × 3) | At 24 per arm (8 × 3) |
|---|---|---|---|
| Pooled within-cell SD, df | 8 | 16 | 32 |
| SD's 95% interval | ×0.68 to ×1.92 | ×0.74 to ×1.52 | about ×0.8 to ×1.3 |
| **Required n built on it** | **×0.46 to ×3.67** | **×0.55 to ×2.32** | about ×0.65 to ×1.75 |
| One arm's SD, df | 4: ×0.60 to ×2.87 | 8: ×0.68 to ×1.92 | 16: ×0.74 to ×1.52 |
| σ_δ, df | **1: ×0.45 to ×31.9, unusable** | 3: ×0.57 to ×3.73 | 7: ×0.66 to ×2.04 |
| Simulated SD estimate if the truth is 2.92 | 1.53 to 4.33 | 1.92 to 3.92 | 2.21 to 3.63 |
| With a 1-in-12 stopper, simulated | 1.8 to 15.5 | 2.4 to 13.5 | 4.9 to 12.3 |

**The stopper rate itself is barely known.** 1 of 12 runs has a 95% Clopper-Pearson interval of 0.2% to 38%. Per arm: no skill 1 of 6 (0.4% to 64%), plugin 0 of 6 (0% to 46%). So whether the plugin prevents this failure mode, a possible real benefit, can't be read from the data. At a true 1 in 12, one arm of 6 sees no stopper 59% of the time, one arm of 12 sees none 35% of the time, and one arm of 24 sees none 12% of the time. **Any SD estimate at 6 or 12 per arm depends on whether a stopper happened to land in the sample: about 2.9 or about 10, and the sample size that follows differs by a factor of 11.**

**What 6 per arm already does show:** on located, a difference over about ±5.6 of 122 (±6% of the mean) is excluded on these two fixtures. That's a real result, and it's about a measure that shouldn't be primary.

### What a budget settles, at $5 per run

Costs exclude fixture writing (1.6 to 1.7 million tokens each, not priced here, and these are real money), judging (0.4 to 0.5 million per test), and overshoot: the runner's cap doesn't stop runs in flight, which took $20 to $31.64. The whole ledger to date is about $180, so these are large asks. Power below uses the plan in section 5: 8 fixtures, per-fixture median differences, signed-rank test, a futility look at halfway. It assumes SD 2.92 for the new measure, which is unknown.

| Budget | Design | Would settle | Wouldn't |
|---|---|---|---|
| $30 to $60 | 1 to 2 × 3 | Catastrophic differences only | Anything else. Repeats today's result |
| $120 | 4 × 3 | A gain of 15% or more of scale, or a clear futility signal | 10% with any confidence |
| **$240** | **8 × 3** | **Whether a gain of about 10% exists, at this size, on this model. Power at +6 of 60: 0.91 to 1.00, or 0.76 to 0.85 with a stopper mode. False win about 2%** | **5%: power 0.37 to 0.68, or 0.30 to 0.52 with a stopper mode** |
| $360 | 12 × 3 | 10% firmly (0.88 to 1.00). 5% as a lean (0.47 to 0.90) | 5% reliably |
| $480 | 16 × 3 | 5% of max on favorable assumptions (0.60 to 0.97) | Anything outside this population |

**No single budget settles** Opus, Codex, new code, very large repositories, or asking. Each is its own population. If the new measure's SD is 5 rather than 2.92, 8 × 3 falls to 0.61 to 0.79 at +6 and 12 × 3 gives 0.79 to 0.96, which is why it should be measured free first (change 1 below).

---

## 5. What's wrong and what to change

### "Significantly improve the quality of code output" can't be tested as stated

- **Quality isn't one quantity.** The owner listed more than 20 attributes, and some trade off. In this data, fixed and new damage correlate at 0.98 on L2.
- **It has no comparator, effect size or weights.** Finding 5 shows the verdict flips with a weight nobody has set: fixed minus w × (damage + unflagged) moves L2 from -7.3 at w = 0 through 0.0 at w = 1 to +7.3 at w = 2. These are post hoc, unweighted by severity, and unflagged isn't always damage, so don't read this as "the plugin wins". Read it as: **the question isn't well-posed until someone picks w.**
- **It has no population.** From cells to monorepos, new code to repair, Claude to Codex. No test covers that, and a win in one says little about another.

**Proposed definition.** A claim takes this form: "For task class T, at size S, on host H and model M, occam at hash X significantly improves quality over no skill." That is true only if, on at least 8 fixtures unseen and unused for tuning, with the fixture as the unit:

1. **Practical:** mean gain on a preregistered composite is at least +10% of the no-skill score.
2. **Statistical:** the 95% interval excludes 0.
3. **No harm:** every preset gate holds.
4. **Human check:** a blind person doesn't contradict it on a sample. For a stronger claim, blind pair preference of at least 15 of 20 (exact p = 0.04).

The composite covers six outcome families, measured by execution wherever possible, with weights the owner sets before any fixture exists:

| Family | Measured by | Covers from the owner's list |
|---|---|---|
| Correct and complete | Hidden behavior and oracles | Incomplete work, expected behavior, goal |
| Safe | Attack oracles; preservation tests | Security, regressions |
| Tested | Mutation score of tests added | Properly tested |
| Maintainable | Follow-on change by a fresh agent; structural oracles | Overengineering, duplication, bloat, reuse, shared code, naming, comments |
| Honest | Report claims against oracle results | Self-critique |
| Well-judged | Decisions against a hidden preference | Asking, permission, correcting what it sees |

"Improves quality" without qualification should mean this holds in at least three of four classes: new code, repair, audit, and decisions. Anything less says which class, and cost goes in the same sentence.

**Owner's decisions needed before any run:** the value of w, whether 10% is the right bar, whether Codex stays in the claim, and how much human review to fund. These aren't things an eval can decide.

### Free changes, ranked

No agent runs. "Tokens" means it needs a model to write something, but no eval runs.

| # | Change | Where | Why | What it lets the owner conclude |
|---|---|---|---|---|
| 1 | **Write executable oracles for the 60 serious defects on L1 and L2** from the key's `trigger` fields. Calibrate: each fails on the starter. Run all 12 saved diffs. Compare with verdicts. *Tokens only* | New `evals/fixtures/*/oracles/`, `evals/audit_comparison.py` | Replaces a reading with a result. Saved diffs make this retroactive, and I confirmed they apply and run in seconds | How often the judge is right, for the first time. An objective fixed count for existing data. The new measure's SD, which sets the budget, before spending it |
| 2 | **Owner sets the definition and w.** | `evals/PREREGISTRATION.md` | Finding 5 | A result that means something either way |
| 3 | **Demote located and proximity decoys to diagnostics.** Parse ranges and lists; match by enclosing function using the AST; report precision and severity-weighted recall; rescore saved reports | `evals/score_audit.py` | Sign flips on format alone | Stops debating noise |
| 4 | **Original-suite check, with triage by root cause** | `evals/audit_comparison.py` (`_tests_pass`), as in my scratch script | "Tests pass" hides test edits | Objective evidence of behavior changed |
| 5 | **Mutation score of agent-added tests on saved diffs** with `mutate` | New script reading `evals/results/*/judge/*.diff` | Plugin adds tests in 6 of 6 runs against 2 of 6, the clearest behavior difference. Do they catch anything? | Whether that's a benefit or just volume |
| 6 | **Define `needs_decision`** in one sentence and re-label; correct the sentence in `docs/evaluation.md` about what those 18 mean | Keys, docs | 17 of 18 cite a rule that wins | Lets fixed be scored fairly |
| 7 | **Freeze the judge.** Store rubric and prompt; scrub "scan", "lead", "tier"; randomize letters per test and defect order; output structured verdicts. Add a second judge on saved data for agreement (*tokens*) | New `evals/judge_rubric.md`, `evals/judge_packet.py` | Unreproducible, leaks arm, unknown reliability | A reliability number |
| 8 | **Statistics.** Fixture as unit, rank-based, intervals in every table, no pooling across plugin hashes, no headline ties without an interval | New `evals/audit_power.py`; `evals/summarize.py`; `RESULTS.md` | "293 against 294" read as a tie; pooling crossed two hashes | Honest uncertainty |
| 9 | **Ceiling gate everywhere.** A comparison needs no-skill pilot pass rate of 20% to 80%, else it's labeled a regression guard and capped at 1 run per arm. Print headroom in reports | `evals/run_eval.sh`, `evals/cost_report.py` | 68% of graded spend went to cases that can't show a gain | Money goes where a gain can appear |
| 10 | **Honest coverage.** Add a "measured as" column; give audits scenario IDs; fail a test if a row cites a not-run scenario as evidence; rename "large" to "medium" | `docs/coverage-map.md`, `evals/scenarios.yaml`, `tests/test_scenarios.py` | See section 1 | A true map of what's known |
| 11 | **Fix diagnostics.** `skill_fired` counts `occam-*`; edits include shell writes (the hook already reads them) | `evals/grade_workspaces.py:162,166` | Both misreport today | Trustworthy process numbers |
| 12 | **A person reads 3 pairs** from L2 with the key closed. About 2 to 3 hours | `evals/BLIND_REVIEW.md` | Pending since the start; no person has looked. Fixed and the judge's rank disagree, and only a person can say which matches what they want | Whether the measures match the owner's actual preference. **Best hours-for-information in this report** |

### Paid changes, ranked

| # | Change | Where | Rough cost | What it lets the owner conclude |
|---|---|---|---|---|
| 1 | **Next audit test** (below) | `evals/audit_comparison.py`, new fixtures | $240 + $40 pilots + fixture cost | Whether a net repair gain of about 10% exists at this size |
| 2 | **Decision harness with a hidden preference.** Each `needs_decision` item has a hidden owner answer, such as clamp rather than reject. A scripted responder answers real questions in a second turn via `claude -p --resume`, whose fit with `claude plugin eval` I haven't verified. Score: asked on those, didn't ask on routine ones, final code matches the preference. Build s23 and s51 on this | New `evals/cases/decisions/`, a small runner | Under $20 on small repos | The first measurement of a stated requirement |
| 3 | **Follow-on change test.** Greenfield specs from an empty repo. Then a fresh no-skill agent makes a preregistered change to each arm's output. Score: its acceptance, cost, and diff size, plus the first agent's hidden tests | New `evals/cases/greenfield/`, `RESULTS.md` "Not measured" row | About $50 to $100 for 8 specs, 3 per arm | Whether generated code is easier to change. **The one design that puts overengineering, duplication, bloat, naming, comments and shared code on an outcome scale** |
| 4 | **Too-large-to-read test.** Rewrite s54 with outcomes: a real repo of at least 150,000 lines at a pinned revision, defects injected by reverting real fix commits or by mutation, with their tests as oracles. Descriptive, 2 repos, 3 per arm | `evals/scenarios.yaml` s54, new fixture | $60+, likely more per run | Whether tools help when reading all of it isn't an option, which is what they're for |
| 5 | **Third-party first.** Local registry mirror; run s04, s05, s06, s53 | New cases, sandbox config | Under $15 | Replaces "nothing" on a named concern |
| 6 | **Concurrent agent.** A scripted second actor edits and claims files during the run; extend s15. Add s16, s17 for subagent count | `evals/cases/` | Under $15 | Whether `coord` changes outcomes, and the first link from agent count to a result |
| 7 | **Codex smoke,** or remove Codex from the claim | `evals/codex_smoke.py` | Your Codex plan | An honest scope |
| 8 | **Ablations, only after a win.** Skill only, hooks only, tools only | `evals/variants/` | As primary | Which part earns its cost |

### Next audit test

**Question.** At 10,000 to 30,000 lines, on Sonnet 5.5, does the full plugin at a frozen hash give more net verified repair than no skill, without more harm, at acceptable cost?

**Fixtures: 8 new, preordered, none read by anyone working on the skill.**

- 4 model-written, from different domains, at least 2 with no numbered rule list, and some outside this model family if available.
- 4 real AI-written repositories, chosen by a rule fixed in advance (the rule in the prereg's real-repository entry is a good start), with defects injected by mutation or by reverting real fix commits, so the oracle is prior behavior.
- At least 30 serious items each, including at least 10 maintainability items with structural oracles (duplicate logic consolidated, dead code gone, needless layer removed), so the primary can see what the owner named.
- **Qualification:** 1 no-skill pilot per fixture, not used in comparison. Primary score must be at most 80% of maximum, or harden it. So $40.

**Arms and control.** Plugin and no skill, 3 runs each per fixture, **24 per arm**. Frozen hash, no plugin edits until the end. Run order randomized within fixture. One fixture at a time under `caffeinate`, with a running total, and other heavy sessions paused.

**Prompt: remove the contradiction.** "Bringing code in line with its documentation is in scope. Anything else that changes behavior goes in a decisions section with your recommendation." Add a structured file, `AUDIT.jsonl`, with `id, file, line, function, severity, status`, so scoring needs no regex.

**Primary measure: net verified repair per run, as a share of the fixture's serious items.**

> (non-decision oracles passing + decision items correctly handled - w × preservation tests newly failing, by root cause) / items

- Correctly handled means left unchanged and raised, or changed and flagged, in line with the hidden preference. w is the owner's, default 2, with w = 1 and 3 reported beside it.
- Writing more earns nothing, since oracles ignore the report apart from one decision credit per item. Citing more earns nothing. Changing more is penalized unless it actually fixes something. Nothing in the primary depends on a model's reading, apart from flag detection on decision items.

**Analysis.** One number per fixture: the difference of medians, plugin minus no skill. Wilcoxon signed-rank across the 8, with Hodges-Lehmann estimate and interval. Report per-fixture results and any stopper-like runs (very low fix rate) by count, per arm.

**Gates.** Each compares plugin against no skill, per run, with its margin fixed in advance.

| Gate | Measure | Fails if |
|---|---|---|
| Regressions | Preservation tests newly failing, by root cause | Upper 95% bound above +1 |
| False claims | Statuses in `AUDIT.jsonl` that oracles contradict | Upper bound above +1 |
| Decoys acted on | Decoy behavior changed, by preservation oracle; reported as defects, by frozen judge | Above +1 |
| Unflagged behavior changes | Judge, frozen rubric | Above +1 |
| Early stops and time-limit hits | Trace | More than +1 of 24 |
| Cost and time | Ledger | Above +30% cost, or twice the time: doesn't undo a win, blocks "recommended", same sentence |
| Human check | A person reads 6 blind pairs before unblinding | Preferring no skill in 5 or more is reported first alongside any win |

**Verdict.** Written down in advance:

- **Helps:** signed-rank significant, estimate at least +10% of no-skill score, all gates pass.
- **Harm:** significant the other way, or any gate fails.
- **No meaningful benefit:** the interval's top is under +10%.
- **Inconclusive:** anything else. Said plainly, and no extra runs are added to resolve it.

**Stopping rule.**

1. **One look, after the first 4 fixtures (12 per arm, $120): futility only.** If the mean of per-fixture median differences is at or below 0, stop and report "no sign of benefit". No early win, because 4 fixtures can't support one. Simulated: false win about 2%, expected cost when there's no effect about $180.
2. **Blinded variance check at that look.** Compute pooled within-cell SD without arm labels. If it's above 4.5, ask the owner whether to extend to 12 fixtures. That doesn't peek at the effect.
3. **Money:** approve the full $240 plus margin before starting. If the cap would bind, stop and report the rest as not run. Don't rely on the runner's cap, which overshoots.
4. **No reruns,** except the existing stalled-run rule. No fixture swaps after seeing results. A follow-up question means new fixtures.

**Operating characteristics, simulated,** for SD 2.92, σ_δ from 0 to 5% of scale, with and without a 1-in-12 stopper in both arms.

| True effect | Chance of "helps" before gates |
|---|---|
| 0 | 2% |
| +2.45 (5% of mean) | 22% to 51% |
| +3 (5% of max) | 30% to 68% |
| +4.9 (10% of mean) | 63% to 98% |
| +6 (10% of max) | 76% to 100% |

**It would let the owner conclude:** net repair at this size, on Sonnet, on fixtures chosen in advance, including some real code. **It wouldn't cover:** gains near 5%, Opus, Codex, new code, repositories too large to read, or asking with a live responder.

**Why not simply rerun.** Another 3 per arm on another fixture at $30 repeats the current design, and repeating it can't improve the construct. Changes 1, 2 and 12 in the free list should come first. Change 1 may also reveal the judge is fine, or that it isn't. That's worth knowing before spending $240.

---

## What I couldn't tell

- **Whether the judge is accurate.** No ground truth exists. One point in its favor, none against, until free change 1.
- **Whether the plugin's restraint is what the owner wants.** It reports more, fixes less and changes less. That's a preference question the data can't settle.
- **How many defects are natural to these fixtures.** I confirmed two, and off-key citations suggest more.
- **The SD of the proposed measure.** Simulations borrow the fixed count's. This is the main assumption in the budget.
- **What fixture writing costs in dollars.** Tokens are recorded; I didn't price them.
- **Whether a two-turn responder fits the current harness.** Unverified.
- **The hard suite.** Not assessed.
- **My keyword classification** of the keys is rough. Counts could shift by a few, and the conclusion that maintainability is nearly absent wouldn't.
- **Everything post hoc here is post hoc:** correlations, rescoring, permutation tests and net-score flips were chosen after seeing the data, on 12 to 18 runs, with no multiplicity correction. They show the measures are fragile. They don't show which arm is better.

## Reproducing the numbers

Each script reads only, and writes to its own directory. All are in `evals/results/eval-audit/scripts/`:

| Script | Produces |
|---|---|
| `extract.py`, `judge2.py`, `conf.py` | Per-run tables, proximity against judge, `needs_decision` split |
| `stats.py` | Per-defect spread, dispersion, correlations |
| `sens.py`, `game.py` | Rescoring rules, synthetic gaming reports |
| `offkey2.py` | Off-key clusters and their distance from keyed lines |
| `accept.py`, `frac.py` | Acceptance by case and arm; fraction of checks |
| `power.py`, `mde.py` | Variance components, intervals, sample sizes, permutation tests, net-score flips |
| `sim.py`, `plan.py`, `plan2.py` | Simulated power and the final plan |
| `orig_tests.py`, `orig2.py`, `orig3.py` | Original suite against each run's final code, sandboxed |
