# Evaluating occam for auditing and repair

`fix`, `reuse`, `debt` and `ledger` were removed on 2026-11-06, because they showed no value on real inputs. Incidents below that name them are history. See `evals/PREREGISTRATION.md`.

Written 2026-11-05. For maintainers and anyone deciding whether to trust this. `evals/RESULTS.md` covers the paid comparison of the earlier skill. This document covers the audit skill and tools added after it.

**In short:**

- **Does it help an agent?** Mixed, and short of the bar set in advance. On the large audit the plugin located about as many defects as no skill and a blind judge scored its repairs higher, though one weak no-skill run drives that. The small audit showed no benefit. [Details.](#does-it-help-an-agent-mixed-and-short-of-the-bar-set-in-advance)
- **Does the scanner work?** Partly. Alone, on a blind test, it located under a fifth of the semantic defects. On real repositories, a model judge called about one lead in three worth acting on and one in eight false. [Details.](#how-well-the-scanner-works)
- **Can the tools be trusted?** Only as far as their last adversarial read. A fresh reviewer, on the same model, found three ways to run or break a user's code, after 400 of the author's own tests had passed. [Details.](#what-independent-review-found)
- **What's unknown?** Whether an agent does better with these tools on code too large to read whole, whether a person agrees with the judgments on real repositories, and anything on Codex. [Details.](#what-has-not-been-checked)

## What the review of occam found

Before this work, occam was a careful skill for making a change and reviewing a diff. Against the brief of auditing and fixing existing AI-generated code at any size, it had real gaps:

| Gap | Before | Now |
|---|---|---|
| Auditing an existing codebase | "Review" meant a diff. No method for a whole repository | `occam-audit`, with strategy by size from a cell to a monorepo |
| Repairing one | Nothing beyond "fix the responsible component" | Tiers that decide permission, locking behavior first, an order of work, batches |
| Tools | None. Every check depended on the model remembering | A standard-library CLI with 16 commands and 189 rules |
| Large repositories | Nothing | `map`, `partition`, `baseline`. 1.5 million lines scanned in about 30 seconds |
| Notebook cells and snippets | Nothing | `scan --stdin`, `.ipynb` parsing, cell locations, hidden-state rules |
| Agent-written defects | Described in prose only | Deterministic rules. The plugin mentions what an edit just introduced, and sends the agent back at stop |
| Goal-based work and plan drift | A sentence about a table in working notes | `goal`: requirements with checks, constraints, scope, stale evidence, drift |
| Other agents | Guidance only | `coord` |
| Codex | Skills only, no tools or hooks | The same tools, plus plugin manifest and hooks, written to the docs and **not run under Codex** |
| Docs | The README and results the docs pointed at were missing when this review began. Another session has since restored them | Present |

The earlier evaluation still stands, and it applies here: the full plugin cost 57% more on the holdout and tied on acceptance. Nothing below shows these additions make agents' output better. It shows the tools work, and how far they can be trusted.

## Does it help an agent? Not in two large tests, and no-skill runs usually fixed more

**Across two large preregistered tests, the plugin located about as many defects as no skill, 92.8 against 93.0 of 122 per run, and typically fixed fewer: median 48.5 of 60 against 55.** The total of 293 against 294 of 360 looks like a tie only because of one no-skill run that fixed 19. Without it, no skill averages 55.0 to the plugin's 48.8. This doesn't support "significantly improves". What changed reliably is how agents behave: plugin runs changed far less code, made fewer unrequested changes, and took longer. These tests also have design problems, listed under "What these tests can't show".

**The latest test first, because the plugin was lower on a primary measure: it fixed fewer serious defects, 50.0 of 60 against 57.3.** It located slightly more, 95.0 of 122 against 94.0. By the rule written before the test repository existed, that's no measured benefit.

The test: a new 28,070-line veterinary platform with 122 planted defects, written by fresh subagents, whose key nobody working on the skill read beforehand. Same prompt and limits as the first large test, 3 runs per arm on Sonnet 5.5, on plugin hash `8cac9607b9697ce0`, which has the larger reader budget and in-place facts but not the fixes from a second review of those hook changes. **It cost $31.64, which is $1.64 over the $30 the user approved.** The runner's $20 limit doesn't stop runs in flight, and I had judged that overshoot unlikely. Run data is in `evals/results/audit-large-2/`.

| Measure | Plugin | No skill |
|---|---:|---:|
| Located of 122, per run (primary) | 93, 91, 101 | 95, 88, 99 |
| Static of 60 | 38, 39, 47 | 40, 34, 43 |
| Semantic of 62 | 55, 52, 54 | 55, 54, 56 |
| Critical and high fixed, of 60 (primary, blind judge) | 48, 49, 53 | 58, 57, 57 |
| Left open but reported | 11, 7, 4 | 1, 1, 2 |
| Missed | 0, 3, 1 | 0, 0, 0 |
| Decoys reported as defects (judge) | 1, 0, 1 | 2, 5, 3 |
| Decoys mentioned (proximity score) | 3, 1, 1 | 2, 1, 3 |
| Items of new damage (judge) | 3, 3, 4 | 6, 6, 6 |
| Report claims the diff contradicts (judge) | 0, 1, 2 | 1, 0, 2 |
| Unflagged behavior changes (judge) | 2, 2, 2 | 7, 7, 6 |
| Judge's rank of 6 | 1st, 5th, 2nd | 6th, 3rd, 4th |
| New test functions | 14, 13, 70 | 0, 83, 61 |
| Lines added | 162, 162, 344 | 679, 1,545, 825 |
| Minutes | 24, 20, 17 | 12, 12, 11 |
| Cost | $13.85 | $17.79 |

Tests passed afterward in all six. The fixed-count means differ by 7.3 and the medians are 49 and 57, so this isn't one outlier, unlike the first large test, where the gap ran the other way. The judge ranked plugin runs 1st and 2nd anyway, on fewer risky changes, while noting that the order is a judgment call and that weighting coverage would change it.

**What the two large tests show together, all of it read after the scores were known:**

| Measure, both tests | Plugin | No skill |
|---|---:|---:|
| Located per run, mean | 92.8 | 93.0 |
| Serious defects fixed, of 360 | 293 | 294 |
| Serious defects fixed per run, median | 48.5 | 55 |
| Lines added, 6 runs | 1,118 | 4,070 |
| Cost, 6 runs | $25.22 | $29.45 |
| Time per run, mean | 17 min | 10 min |

- **Three runs per arm can't settle this.** Mean fixed counts favored the plugin by 7 in one test and no skill by 7 in the other.
- **The skill still holds agents back from fixing,** which is the failure the brief warned about. In the latest test it left 22 serious defects open against 4, and the judge called plugin runs over-cautious 10 times against 0, despite the rule added so that documented behavior gets fixed. Part of that restraint is correct: no-skill runs reported 5 times as many decoys as defects, caused more damage, and made 3 times as many unflagged behavior changes. This trade is the real finding.
- **Restraint doesn't prevent every error.** The worst new damage in the latest test was a plugin run's: its backup rewrite keeps 10 files when 20 exist, and 1 when 29 do, which I confirmed by running the slice, and its report says backups keep the newest 30. A no-skill run put every GET inside a write transaction, which the judge found and I confirmed in the diff.
- **More readers helped little if at all.** `map` advised 6 readers. Plugin runs used 4 or 5, and no-skill runs used 8 to 10 agents in total. Semantic located rose from 51.3 to 53.7 with the plugin, but on a different fixture, so it's not a measurement of that change.
- **The scanner remains weak on its own.** Its blind score on this fixture is below, and it can't be what makes the difference.

### What these tests can't show

An independent audit of the eval suite, in `evals/EVAL_AUDIT.md`, found that the audit tests measure less than they appear to. I checked its main numbers against the data. None of this changes the tables above, but it limits what they mean:

- **Most of what the owner named has no outcome test.** Of 33 things checked, 7 have an outcome measure with a comparison arm and room to move. All 60 judged defects per fixture are security, business-rule or reliability bugs, so these tests can't see overengineering, duplication, comments, naming, base classes or third-party choices.
- **"Located" is mostly citation-format noise.** Parsing line ranges properly flips the sign of the difference between arms on both large fixtures, from -1.3 to +0.4 and from +1.0 to -1.4. It shouldn't be a primary measure.
- **"Fixed" rewards changing more.** On the latest fixture it correlates 0.98 with new damage and -0.65 with the same judge's overall score, and the run that fixed the most ranked last.
- **The verdict depends on a weight nobody has set.** Count fixes alone, and no skill leads on medians in all three fixtures. Charge 2 fixes per new bug or unflagged change, and the plugin leads on means in all three. That's post hoc, and it shows the question isn't settled by these numbers either way.
- **The prompt, README and key disagree.** Both arms were told not to change public behavior, then scored on fixes that do. The key marks 18 serious defects on the latest fixture `needs_decision`, yet 17 of them cite a README rule, and the README says the rule wins. So no-skill runs fixing them wasn't skipping permission, as I first wrote here. The flag is undefined and needs relabeling.
- **Nothing tests asking.** Every case has nobody to answer, so a stated requirement is unmeasured.
- **"Large" isn't large.** These fixtures have about 15,000 source lines plus 12,000 of tests, and plugin reports say readers read every line. Nothing tests code too large to read, which is what the tools are for.
- **The fixture is the independent unit, and there are two.** In simulation, 12 runs per cell on 2 fixtures reads as significant 46% of the time with no true effect. More runs on the same repositories wouldn't help.

**The key to this fixture reached two scratch copies** made by another session at 02:46, which says it read neither and has deleted both. No plugin edit from that session entered this snapshot.

## The first large test

**The latest test doesn't meet the bar: the plugin located slightly fewer defects (90.7 of 122 against 92.0), and its mechanical decoy score was higher.** By the rule written before the test repository existed, that's no measured benefit. Its repairs did look better on a blind read: more defects fixed on average, regression tests in every run, and no unflagged behavior changes. That doesn't establish "significantly improves", which needs more than this one test.

The test: a new 27,369-line logistics platform with 122 planted defects, written by fresh subagents, whose key nobody working on the skill read beforehand. Audit-and-fix prompt, 3 runs per arm on Sonnet 5.5, $23.03 in all, on plugin hash `d913a354a88b89a1`. The rules are in `evals/PREREGISTRATION.md`, and the run data is in `evals/results/audit-large/`. That cost passed the $19 given to the runner, because runs in flight overshoot, and stayed inside the user's $25.

**First primary measure: a report names the defect's file and a line within 3.**

| Arm | Run | Located of 122 | Static of 60 | Semantic of 62 | Critical of 20 | Decoys of 43 | Tests pass | New tests | Lines added | Cost | Minutes |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| Plugin | 0 | 90 | 38 | 52 | 17 | 6 | Yes | 17 | 144 | $3.39 | 12 |
| Plugin | 1 | 94 | 41 | 53 | 19 | 5 | Yes | 20 | 137 | $4.07 | 13 |
| Plugin | 2 | 88 | 39 | 49 | 18 | 6 | Yes | 12 | 169 | $3.91 | 16 |
| No skill | 0 | 94 | 38 | 56 | 18 | 2 | Yes | 0 | 813 | $5.22 | 8 |
| No skill | 1 | 91 | 34 | 57 | 18 | 0 | Yes | 0 | 140 | $3.34 | 9 |
| No skill | 2 | 91 | 36 | 55 | 19 | 5 | Yes | 0 | 68 | $3.10 | 6 |

Means: located 90.7 against 92.0, static 39.3 against 36.0, semantic 51.3 against 56.0.

**Second primary measure: a blind subagent judge read each report and diff for the 60 critical and high defects.** It's the same model family, and it ran nothing.

| Arm | Run | Fixed | Partial | Reported, left open | Missed | Report claims the diff contradicts | Unflagged behavior changes | Overall of 5 | Rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Plugin | 0 | 48 | 3 | 8 | 1 | 1 | 0 | 4 | 2nd |
| Plugin | 1 | 43 | 2 | 13 | 2 | 4 | 0 | 3 | 5th |
| Plugin | 2 | 52 | 1 | 4 | 3 | 0 | 0 | 4 | 1st |
| No skill | 0 | 53 | 3 | 4 | 0 | 4 | 7 | 3 | 3rd |
| No skill | 1 | 50 | 2 | 7 | 1 | 1 | 1 | 3 | 4th |
| No skill | 2 | 19 | 2 | 38 | 1 | 0 | 0 | 2 | 6th |

Mean fixed is 47.7 against 40.7, but one no-skill run that treated "behavior change" as a reason to stop drives that. The other two no-skill runs fixed 53 and 50, so the medians are 48 and 50.

**What this shows, all of it read after the scores were known:**

- **The tools were used this time.** All three plugin runs ran `scan`, two to four times each, after `map` began printing leads and the skill's definition of done required it. In the first test, none did.
- **The tools added finds, and reading lost ground.** On the 27 defects the scanner flags, plugin runs located 63 of a possible 81, against 49. On the other 95, they located 209 of 285, against 227. All three plugin runs split reading into exactly 3 agents, as `map` advised at 12,000 lines per reader. No-skill runs chose 5 or 6, and found more semantic defects. That's a lead, not an established cause. The budget has since dropped to 5,000 lines per reader, unmeasured.
- **The decoy score overstates the plugin's errors.** It counts any mention, and 11 of 18 mentions I checked in plugin reports were scanner leads the agents correctly dismissed with a reason. Without those, the arms are about level, at around 7 each. By the rule fixed in advance, the score stands at 17 against 7.
- **Repairs were more disciplined.** Every plugin run added regression tests, and no no-skill run added any. One no-skill report says a reused idempotency key "gives 422", while its diff raises `UnprocessableEntity` without importing it, so that path is a `NameError`. I confirmed this in the code, and replaying the scanner on that final tree names the line. Plugin runs still made false claims too: one said all its new tests fail on the original code, and the judge found at least three that pass there.
- **It costs time, not money.** $11.37 against $11.66, but about 1.8 times as long, with more test runs.
- **Enforcement can't be confirmed from these traces.** Agents edited through `python3 - <<E` scripts, with no `Edit` calls in any plugin run. Replaying 47 such commands through the current hook, 29 name their file, 14 are seen with no clear path, and 4 go unseen. Stop couldn't scan a file it couldn't name, and stop feedback isn't recorded in traces, so whether the audit check fired in these runs is unknown. The hook now reads more of those paths from the script's syntax, unmeasured.

**What this can't show.** One fixture, written by the model family that ran and judged it. Tests are thin in every arm, so fix counts overstate safety. Nothing here covers code too large to split among readers. `plugin/` has changed since the snapshot.

## The first test, on a small repository

**No measured benefit for auditing and repair, and the plugin arm came out behind.** On the preregistered measure it located slightly fewer defects, and a blind read of the repairs ranked all three no-skill runs above all three plugin runs. This doesn't support "significantly improves output".

The test: the same audit-and-fix prompt on the blind fixture, a 3,064-line Python service with 83 planted defects, 3 runs per arm on Sonnet 5.5, $8.58 in all. Rules were written down first in `evals/PREREGISTRATION.md`. The run used plugin hash `747c59cbfe9c3eae`. The ledger records `120a5adc54167dd9` because the script hashed the plugin after the run, by which time another session had narrowed a hold in `plugin/hooks`. The runs used a snapshot from the start, so that value is wrong, and the script now hashes first. Run data is in `evals/results/audit-sonnet/`.

**Preregistered measure: a report names the defect's file and a line within 3.**

| Arm | Run | Located of 83 | Static of 41 | Semantic of 42 | Critical of 12 | Decoys of 27 | Tests pass | Lines added | Cost |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| Plugin | 0 | 57 | 27 | 30 | 11 | 0 | Yes | 342 | $1.47 |
| Plugin | 1 | 61 | 31 | 30 | 12 | 2 | Yes | 166 | $1.01 |
| Plugin | 2 | 33 | 19 | 14 | 10 | 0 | Yes | 283 | $1.83 |
| No skill | 0 | 61 | 31 | 30 | 11 | 3 | Yes | 777 | $1.55 |
| No skill | 1 | 60 | 31 | 29 | 11 | 0 | Yes | 370 | $1.37 |
| No skill | 2 | 42 | 21 | 21 | 7 | 1 | Yes | 589 | $1.36 |

Means: 50.3 located with the plugin, 54.3 without. Three runs per arm supports no significance claim. This measure also has a flaw: reports citing post-edit line numbers lose credit, which is at least part of why both run 2s score low.

**Added afterward, not preregistered: a blind judge.** Proximity can't say whether a repair worked, so a fresh subagent read each report and diff with the arms hidden and tool names removed, then judged the 42 critical and high defects. It's the same model family and ran nothing. I confirmed its headline false claim against the diff. The rest is its reading.

| Arm | Run | Fixed | Partial | Reported, left open | Missed | Wrong | Report claims the diff contradicts | Unflagged behavior changes | Overall of 5 | Rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Plugin | 0 | 31 | 4 | 5 | 1 | 1 | 6 | 3 | 2 | 6th |
| Plugin | 1 | 27 | 3 | 10 | 2 | 0 | 0 | 2 | 3 | 5th |
| Plugin | 2 | 31 | 3 | 8 | 0 | 0 | 4 | 2 | 3 | 4th |
| No skill | 0 | 34 | 2 | 5 | 1 | 0 | 1 | 6 | 4 | 2nd |
| No skill | 1 | 34 | 3 | 5 | 0 | 0 | 2 | 4 | 4 | 3rd |
| No skill | 2 | 33 | 3 | 6 | 0 | 0 | 0 | 4 | 4 | 1st |

**What went wrong in the plugin arm:**

- **The tools weren't used.** All three runs ran `occam map`, read "small repository", said some version of "I'll read it all", and never ran `scan`, `gate`, `coord` or anything else. So this measured the skill's text and hooks, not the scanner. `map` had already scanned, but it printed only counts.
- **It held back on things it should have fixed.** 89 fixes against 101 of 126, and 23 left open against 16. All three plugin runs left a key in `static/checkout.js`, one saying that removing it would break the widget. All three no-skill runs removed it and said the widget now needs a token. The skill did call secrets a matter for a person, though I can't show that's why. One held invoice rules the README states outright. This is the failure the brief warned about: keeping things small isn't enough when something is wrong.
- **One report claimed a fix that didn't exist.** It marked `config.py:50` fixed and said `SUBLEDGER_DEBUG=false` now means off. The line was unchanged, so debug stays on with the example config, and tracebacks reach clients. `scan` flags that exact line. A reviewer agent ran on that diff, and the claim still went out.

**What it did better, on small numbers:** half the code added on average (264 lines against 579), half the unflagged behavior changes (7 against 14), fewer decoys (2 against 4), more critical defects located (33 of 36 against 29), and all three runs stated a workload against none. Cost was level ($4.31 against $4.28). Less code isn't a success by itself, and here it came with fewer fixes.

**Both arms** left the refund stub, the PDF endpoint and the global email constraint unfixed, and most made the retry double-charge easier to reach by adding timeouts.

**What this can't show.** One small fixture, whose key the skill's author had read. A 3,000-line repository can be read whole, so it can't test what the tools are for, which is code too large to read. Whether the plugin helps there is unknown.

**Changed afterward, unmeasured.** None of this has run against an agent:

- `map` now prints the worst 10 leads, above everything else, so an agent gets them whether or not it runs `scan`.
- The skill's definition of done now requires a scan at every size, and rereading the diff against the report.
- At stop, an audit session is told what the scanner still raises in files it changed. Replayed on the six final trees, this names `config.py:50` for the run with the false claim, and otherwise lists 1 or 2 items.
- A rule the documentation states is now tier B, even for money. Fixing it means listing the visible change.
- Committed secrets are tier B: move the value out and tell a person to rotate it.

## One agent on a real repository

One Sonnet subagent followed the skill on a private copy of a real, mostly AI-written billing app of 33,021 lines, asked to audit it and fix what it safely could. There's no comparison arm, so this says nothing about improvement. Because the code was untrusted, it wasn't allowed to run it, so no test ran. Subagents also skip the holds and the stop checks, so most of the hooks didn't apply.

- **The scanner did its job.** An `undefined-name` lead found the one bug it fixed: `_fernet` was used in `server.py` and never imported, so two admin endpoints raised `NameError` on every call. I confirmed this in the code.
- **The audit was shallow.** It took 76 seconds and 62,852 tokens, read little, and reported 5 main findings. Its own "not checked" list included billing logic beyond skimming and tenancy checks across 91 routes, and it never mentioned 27 `float-money` leads in a billing app. Its report was honest about this, but honest isn't the same as finished. The skill's definition of done now requires reading the money and auth paths, or naming the ones too large to reach, and confirming or dismissing every critical and high lead.
- **It left things it could have fixed,** like a date-parse error it could have logged. With no tests to run, the skill's rule that a check must protect a repair held it back, which may be the right call here.
- **Tool problems it reported:** 103 of the leads were `pip freeze` output read as unused dependencies, since fixed. It avoided `ruff` for fear of running repository code, so `tools` now says which tools only read. JavaScript and SQL, most of this repository, get weak coverage, and that isn't fixed.

## Common problems, and what addresses each

"Rule" means the scanner can flag it. "Skill" means guidance only, which a model may skip. Anything marked **judgment** can't be caught by a tool.

| Problem | Tool or rule | Skill |
|---|---|---|
| Overengineering | `single-impl-abstraction`, `pass-through`, `pattern-one-product`, `one-method-class`, `static-only-class`, `deep-inheritance`. Whether a layer is warranted is **judgment** | Core, design |
| Duplication | `clone-block`, `clone-renamed`, `clone-function`, `diverged-twin`, `parallel-verbs`, and `gate` on new names | Design, repair |
| Overly complex algorithms | `high-complexity`, `deep-nesting`, `nested-loops`, `nested-same-collection`, `list-membership-in-loop`, `bench`'s growth fit | Design, performance |
| Not looking for third-party first | `deps`, `handrolled-*`, `tools` | Core |
| Bloat | `scratch-file`, `ai-report-file`, `committed-artifact`, `unused-dependency`, `competing-dependencies`, `utility-bucket`, `debug-leftover`, dead-code rules | Design, repair |
| Non-scalable architecture | `process-local-state`, `unpaginated-query`, `query-in-loop`, `unbounded-concurrency`, `materialize-all`, `import-time-io`, `import-cycle`, `hub-module` | Performance, design |
| Not properly tested | `no-tests`, `module-untested`, `test-*`, `checks-hidden-by-config`, `mutate`, `gate` on weakened tests | Verification, repair |
| Not critiquing its own work | `gate`, and the scan at stop | Critique, then converge |
| Security | 27 rules, and `tools` for scanners. Tenancy and logic flaws are **judgment** | Security |
| Usability | `generic-exception`, `opaque-error`, `inconsistent-return`, `a11y-missing`, `rest-verb-route`, `many-params`, `flag-params`. Most of this is **judgment** | Design |
| Comments, too many or too few | `ai-residue`, `narration-comment`, `comment-flood`, `banner-comment`, `missing-docstring`, `docstring-restates-name` | Design |
| Not reusing code | `query find`, `gate`, `parallel-verbs` | Core |
| Shared code and base classes | `pull-up-method`, `base-class-bypassed`, `lsp-violation`, `single-impl-abstraction` | Design |
| Other agents | `coord`, `partition --mode write` | Collaboration |
| Language best practices | `deprecated-api`, `mutable-default`, `float-money`, `star-import` and others. Python parsed, others at text level | Language skills |
| Performance and expected behavior | `bench`, `golden`, `mutate`, and performance rules | Performance, verification |
| Not sticking to the plan | `goal verify` constraints and scope drift | Know what done means |
| Incomplete implementation | `stub-*`, `truncation-marker`, `fake-success`, `fake-data`, `orphan-module`, and `gate` on new code nothing calls | Core |
| Goal-based operation | `goal`, `goal condition` for a host's goal mode | Collaboration |
| Number of subagents | `map`, `partition`. The numbers are heuristics | Scale, collaboration |
| Architecture down to hardware | Rules tagged by layer. `map` lists implicated layers. `dataframe-grow-loop`, `python-loop-over-array`, `transfer-in-loop`, `remote-get-in-loop`, `oversubscription` | Design |
| Standard naming | `hedge-name`, `vague-name`, `convention-mismatch`, `rest-verb-route`. Whether a name is the industry's term is **judgment** | Design |
| Fixing, while asking | Tiers, the audit-only read-only hook | Repair, and "When you find something else" in the core |

## How well the scanner works

Free measurements on Python 3.14, an arm64 laptop with 12 CPUs. None of them involve a model.

**Rule behavior.** Every rule has a case that must fire and a near miss that mustn't, enforced by a test that fails if a rule has none.

**On code that isn't AI-generated.** Python's standard library, about 300,000 lines, is a control: mature code that does much of this deliberately. `undefined-name`, `phantom-local-import`, `fake-success` and `truncation-marker` found nothing there, after handling dynamic modules. `phantom-attribute` has 11 hits, all on platform-specific or private names. It still has about 3,600 findings at all confidences, mostly complexity and duplication, which are true of that code and don't make it defective. Expect many leads on any large repository. That's why they are labeled leads, and sorted.

**Speed.** 1.5 million lines, built by repeating the standard library: 21 to 31 seconds cold on 8 workers, 3.4 seconds with the cache, about 780 MB. Before profiling, the same scan took 210 seconds because of quadratic clone expansion, which is now linear.

**Hostile input.** A repository can't be trusted, so input is tested for what it could do to the scanner. Several patterns went quadratic when tested, including a regular expression written during this work, and they're fixed. Tests now hold nine shapes of hostile input per language to a time limit, and hooks have their own time limit as well.

**On real AI-written code.** The stdlib control and the fixture had hidden how badly some rules behave on real projects. Eight public repositories tagged as vibe-coded or built with Claude Code, from 376 lines to 1.47 million, gave 13,114 critical and high leads on the first run, and most of the largest groups were false alarms:

| Rule | Leads | What it got wrong |
|---|---:|---|
| `phantom-local-import` | 3,347 | Read `json.dumps` as a project's own `foundation/json.py`, and `from alembic import op` as a local folder |
| `test-no-assert` | 3,217 | Missed asserts in a nested `async def scenario()`, or in a helper the test calls |
| `secret-compare` | 803 | Called any `digest` or `*_signature` a secret, including cache keys |
| `query-in-loop` | 737 | Counted loops in tests and migrations, over two written-out table names, and retries |
| `missing-await` | 75 | Flagged `return res.json()`, which is correct |

`phantom-import` also had a real parsing bug: one requirement with extras, like `"httpx[socks]"`, ended the dependency list, so everything after it read as undeclared. After fixing these, the same repositories give 4,382 critical and high leads, a drop of 67%, while the fixture still scores 29 of 41 and 5 of 42. The standard library with its tests, about 1 million lines, went from 698 `phantom-local-import` leads to 19, all in the tests of the import system and `inspect`. The earlier control left those tests out, so it never saw these errors.

Those eight repositories were tuning data, so the check came from seven others the rules hadn't seen: 5 Python and 2 TypeScript, 290 to 33,021 lines, chosen by a rule fixed in advance, and 6 of them with AI-attributed commits. A fresh subagent read the code for 103 randomly sampled leads:

| | Leads | Worth fixing or a look | True but minor | False |
|---|---:|---:|---:|---:|
| All | 103 | 32 (31%) | 59 (57%) | 12 (12%) |
| Critical and high | 72 | 26 (36%) | 37 (51%) | 9 (13%) |
| Python repositories | 74 | 26 (35%) | 37 (50%) | 11 (15%) |
| TypeScript repositories | 29 | 6 (21%) | 22 (76%) | 1 (3%) |

So about one lead in three deserves action and one in eight is wrong, which is why the skill calls them leads and tells the agent to confirm them. This is one model's judgment, on a small sample. `swallowed-exception` was the noisiest large rule, with 11 of 14 true but minor, so it now ranks high only in files handling money, auth and the like.

Ten of the 12 false leads were then fixed. The worst was `unused-import` missing uses inside f-strings, because it read a view with strings blanked. Also fixed: modules Python has removed, like `audioop`, called invented; two calls compared in a test called a tautology; SQL from a loop over written-out names; and a retry loop called per item. Two remain: a handler that logs at debug level still counts as dropping the error, and config files whose keys match but whose values differ can read as clones. The percentages above are from before these fixes, and re-judging the same sample would inflate them, so no number exists for the current version.

**Speed on real code.** 1.47 million lines in 41 seconds and 1.34 million in 34, with no cache. `map` puts leads like missing auth checks in a billing app at the top. Whether an agent acts on them better than it would alone is still untested.

**The scanner's one truly blind score.** On the large fixture, whose key nobody working on the rules had read, at medium confidence and up: 22 of 60 static defects, 5 of 62 semantic, 2 of 20 critical, and 7 of 43 decoys. At all confidences: 33 of 60, 13 of 62, 10 of 20 critical, 12 of 43 decoys. On the second large fixture, also blind: 20 of 60 static, 2 of 62 semantic, 1 of 20 critical and 4 of 42 decoys, and at all confidences 26 of 60, 6 of 62, 6 of 20 critical and 6 of 42 decoys. Those are the numbers to trust over the next one, which came from a fixture the rules were later tuned on.

**A blind test.** A fresh subagent, told nothing about the rules, wrote a 3,200-line AI-style service with 83 planted defects and 27 decoys, listing them only in a key. The numbers below are for medium confidence and up, the default, and count a defect as located if a finding lands within 3 lines. That measures pointing at the right place, not understanding.

| | First run, before anyone read the key | After rules were added from the misses |
|---|---|---|
| Defects a pattern could catch (41) | **20** | 29 |
| Defects needing semantics (42) | **8** | 5 |
| Critical (12) | **5** | 4 |
| Decoys flagged, of 27 | 8 | 6 |
| Findings near a planted defect | 26 of 69 | 34 of 61 |

**The first column is the honest result.** The second is development data, since the key had been read, and it can only show the gaps were real. Some semantic and critical matches fell because moving `select-star` to low confidence removed findings that had landed near a defect by accident, which shows how crude proximity scoring is.

What this means: **the scanner alone misses most of what matters.** It locates about half of what a pattern could catch, cold, and under a fifth of the semantic defects, which include things like a tenant leak or proration disagreeing with the README. That's why the skill makes reading a required step and treats the scanner as a starting point. Whether an agent with the skill finds more than one without it hasn't been measured.

**Its own code.** The scanner found real problems in itself during this work: a false positive on comprehensions, complexity in rule functions, per-row database writes. It reports no high-severity finding on its own tools now, apart from suppressions that state a reason.

## What independent review found

A fresh reviewer, same model, was given the code and requirements but not my conclusions, and told to break it. Its verdict was "not ready", and it was right. Everything below reproduced, and each now has a regression test in `tests/test_review_regressions.py`.

| Severity | What it found | Fix |
|---|---|---|
| Critical | `scan` could run repository code. With 150 or more files, spawned workers had the working directory on `sys.path`, so a committed `multiprocessing.py` ran | Workers start in an empty folder |
| Critical | A repository delivered with `.git` could make git run programs (hooks, filters, `gpg.program`), including from `coord status`, the skill's first move. It could also plant the tools' state, so `goal verify` ran its commands | Every route we know is switched off for each git call, and state moved outside the repository |
| Critical | `fix --apply` broke code and called it proven: `import os, re; import sys` lost `sys`, side-effect imports were removed, and a `# Here is...` line inside a Java text block or shell heredoc was deleted | Rewritten. Python only, and comments only by default. Import removal is opt-in, because a second review showed it can't be proven safe |
| High | `fix` overwrote work in untracked folders and outside git, and ignored folder claims | All refused now |
| High | `gate` gave false all-clears on names with spaces, a bad `--base`, deleted tests, renamed tests with assertions dropped, syntax errors, and `# Generated by ChatGPT` headers, which hid the whole file | Each handled, or reported as unchecked |
| High | `goal verify` said ALL VERIFIED with a forbidden file deleted | Deletions and renames count |
| High | Concurrent `coord claim` granted one path to several agents, and `goal add` lost entries | Transactions, and a required `--owner` |
| High | `ledger sync` erased triage notes and marked findings fixed when a file merely stopped parsing | A closure now needs a real read of the file |
| Medium | Audit-only wasn't held for "Can you audit this repo?", `occam fix --apply`, or anything on Codex | All held |
| Medium | `fix` deleted comments carrying real reasons and a license notice | Only a plain assistant voice with no reason given |
| Medium | `partition` called Go, Java and aliased TypeScript independent, `map` said "cell: 0 lines" for 180,000 lines of Dart, and a strange notebook or `.occam.json` crashed a whole scan | Fixed |

The scale of this list matters more than any one item. The tools passed 400 tests written by their author before an independent read found three ways to run or break a user's code. That's the argument for a fresh reviewer, and a reason to treat anything here as only as trustworthy as its last adversarial read.

Two more independent reviews followed, each given the code and not my conclusions, and regression tests cover what they found.

- **The second** found a regression I had introduced: marking git filters required turned a git failure into "No changes". It also found more ways `fix` could break code, which is why import removal became opt-in, along with further ways to run programs, false holds, and races in `goal`.
- **The third** found `gate` missing findings on unchanged lines, pure renames and submodules, holds that fired on build requests, and two more `fix` cases: coding lines and computed globals.

Two known problems are left. With a blanked filter that isn't marked required, `coord status` can list a file as dirty that git doesn't show, which errs toward caution. On a bare repository, `map` and `coord status` exit with code 2.

## What has not been checked

- **Whether changes after the second large test help.** No agent has run them. A fair retest needs a new fixture, and enough runs to detect a small gap.
- **Very large code.** The largest agent test is 28,070 lines. Nothing tests an agent with these tools on code too large to split among readers.
- **Codex.** The manifest, hooks and marketplace entry follow the docs, and were tested by feeding the script documented events. Codex wasn't available here. Whether skills in `.agents/skills` can reach sibling `scripts/` on every host hasn't been observed.
- **Audits of real AI-generated repositories.** The scanner has run on 15, with leads judged by a model. One agent has audited one, without running its tests, most of the hooks or a comparison. No person has reviewed any of this.
- **Languages other than Python.** They get text and brace-level rules, with no parser, so treat them as weak. Real code was scanned for false positives: npm's own source (14,000 lines of JavaScript), 40 Rust crates (278,000 lines) and 3 Go modules (32,000 lines). That found and fixed whole classes of false alarm, such as doc-comment examples reported as dead code, a crate's own name reported as phantom, and Go's `interface{}` return type read as an empty body. Java, Kotlin, C, C++, C#, Ruby, PHP and Swift have only the rule tests.
- **Third-party tool entries.** `tools` lists analyzers from their documentation. Only ruff and mypy are installed here, so most invocations haven't been run.
- **`deps --online`.** Written against registry APIs and not exercised against the live registries in tests, so that tests stay offline.
- **Windows and Linux.** Not run. `bench` uses `os.wait4`, which Windows doesn't have.
- **Thresholds.** The complexity and size numbers are review triggers chosen by judgment, except the 1,000-line module trigger, which is pylint's default.
