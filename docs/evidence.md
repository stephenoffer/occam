# What was tested, and what it showed

For anyone deciding whether to trust occam. The full record, with every table and caveat, is in [`evals/RESULTS.md`](../evals/RESULTS.md). The audit tools have their own write-up in [`evaluation.md`](evaluation.md).

## The short version

**In this evaluation, the plugin made agents follow the process. It did not make the software measurably better overall, and it cost more. It showed one real risk, which did not recur in a small re-run after a fix, though that doesn't show the fix was the reason.**

| Holdout, Opus 5.5, 3 cases, 3 runs each | Acceptance | Cost | Hit the time limit |
|---|---:|---:|---:|
| No skill | 9/9 | $5.29 | 0/9 |
| Compact skill | 8/9 | $5.08 | 2/9 |
| Full plugin | 8/9 | $8.32 (+57%) | 2/9 |

- **Sonnet 5.5:** the plugin passed 8/9 against 9/9 with no skill. That's one real failure in a small sample, and it doesn't establish a cause.
- **The Opus failures are silent regressions,** one of them wrong arithmetic, in runs stopped at the time limit. The tests first missed them and all three arms scored 9/9. These scores include a check added afterward. No run that finished regressed.
- **After a fix.** Rewrites now get a rule to compare old and new, and a hook note. On a fresh case, the plugin and no skill both passed 3/3, and the plugin cost 40% more and took about twice as long. On the case that failed, the plugin passed 3/3 with no timeouts. The samples are small, the no-skill runs on the fresh case made the same comparison unprompted, and machine load and other changes can't be ruled out.
- **Python guidance:** no measured benefit on seven new Sonnet cases, at about 23% more cost per run, and the new references were read in only 1 of 21 plugin runs. Direct pointers to them, tested afterwards on five of those cases, didn't change that: 1 of 15. A later case on moved APIs and sinks tied at 3/3, at about 35% more cost per run.
- **A possible gain.** A blind model judge scored skill-arm code as simpler when the run finished, with no difference on whether it would merge it. That's a lead, not a measurement. Human review is still pending.
- **Less code, at more cost.** From saved diffs, after the fact and not preregistered: plugin runs delivered 0.72 times the source lines of no skill on the Opus holdout and 0.79 on Sonnet, while costing more (+57% in total on Opus). That's three cases, and less code isn't better code by itself. See "Code size from saved runs" in [`evals/RESULTS.md`](../evals/RESULTS.md).
- **What it demonstrably changes is behavior.** Every hold in the holdout version fired in real runs, and a check after the last edit went from 12/14 runs to 14/14 on the development cases.

These cases were almost all at the ceiling before any skill existed, so a benefit on harder or larger work is possible, and this suite can't establish it. Install the full plugin if you want enforcement, not because you expect a measured quality gain.

## Hard cases

**No sign of a benefit, at more cost.** A preregistered round on 8 fresh cases stopped at its pilot because no skill passed 5 of them, so it says nothing about the plugin. An exploratory look at the other 3 on Sonnet 5.5, not a round, had the plugin passing 3 of 9 runs against 4 of 9 with no skill, at 64% more cost and twice the turns. It also exposed a real defect: a hook send-back could replace a good report with a short reply to a note the reader never sees. The closing text of those send-backs now asks for the whole report again, and no agent has run that yet. See "Hard cases" in [`evals/RESULTS.md`](../evals/RESULTS.md).

## Auditing and repair

**No measured benefit in finding or fixing, with more restrained changes.** Across two large tests of about 28,000 lines, 3 runs per arm each, the plugin located 92.8 of 122 per run against 93.0. It fixed a median of 48.5 of 60 serious defects against 55; totals of 293 and 294 of 360 look level only because one no-skill run fixed 19. In the latest test it fixed fewer, 50.0 of 60 against 57.3, and left 22 open against 4. It also reported fewer decoys as defects (2 against 10), caused less new damage (10 items against 18), made fewer unflagged behavior changes (6 against 20), added about a quarter of the code, and cost about 14% less over both tests, while taking about 1.8 times as long. An earlier test on a 3,000-line repository also found no benefit. These tests have design problems, including a prompt telling agents not to change behavior while scoring fixes that do, which `evaluation.md` lists.

**The scanner on real code.** On seven real repositories it hadn't been tuned on, mostly AI-written, a blind model judge called 31% of 103 sampled leads worth acting on, 57% true but minor, and 12% false. Getting there took rule fixes that cut critical and high leads on eight other repositories by 67%, so earlier scanner numbers from synthetic code overstated its precision. One agent then audited a real 33,000-line billing app with the skill: the scanner led it to a real crash bug, but the audit was too shallow, stopping after 76 seconds with billing logic unread. [`evaluation.md`](evaluation.md) has the details.

## What each combination has been through

Unless a row says otherwise, this describes the plugin at hash `ee947fc74a0dc453`. Anything added to `plugin/` after that, including `skills/occam/scripts/`, `skills/occam-audit/`, the `occam-python` references, the hook's Python handling, the failure-mode checks, the wording and checks from the Karpathy and Ponytail review and the shared design doc, was built by other sessions. It has been through at most the small re-evaluation at hash `6e9b898640b2ac71`, not the holdout comparison, and later changes haven't been through either. See the change log in [`evals/PREREGISTRATION.md`](../evals/PREREGISTRATION.md).

| Combination | Status |
|---|---|
| Claude Code 2.1.318 with the plugin: end to end, smoke, holdout | **Verified** on real runs, with Opus 5.5 and Sonnet 5.5 |
| Re-evaluation at `6e9b898640b2ac71`: one fresh case, and two holdout cases again | **Run** on Opus 5.5, 7 plugin runs and 3 no-skill runs. See [`evals/RESULTS.md`](../evals/RESULTS.md) |
| `marketplace add` and `install` | **Verified** in a throwaway config: installs and lists 9 skills, 1 agent, 8 hook events. The plugin has since grown, and `claude plugin details occam@occam` lists 11 skills, 2 agents and 8 hook events |
| Plain copy into `.claude/skills/` | **Verified** discovery of all 9 skills that existed then, one run |
| Enforcement hook logic | **Verified** by the free test suite, 1,789 passed and 1 skipped on plugin `149ee2eb0ed964ca`. The 540 tests of the main hook and its failure-mode checks also passed on the stock macOS Python 3.9 |
| Failure-mode checks | **Verified** by deterministic tests on cases we wrote, in `tests/test_failure_modes.py`. **Partly seen** in real runs (holds, person-confirm asks, failed-check note). The web denial and a Stop comparison sending an agent back have **not** been seen, and their effect alone isn't measured. The rule on changes right after a failed check was narrowed after these runs, using their traces |
| `occam docs`, the `occam-docs` skill and the human-voice handoff | **Verified** by the free tests in `tests/test_docs_tool.py`, and by hand against the real human-voice linter at 0.1.0 and 0.9.0 on one small sample project. Run on 20 existing documents and six saved audit reports, where it found no real mistake and its 59 leads were all explainable. **Not run** on an agent: no evidence yet that agents use it or that their documents improve. It adds about 100 always-on tokens per session |
| Codex | **Not run**: dropped for now, so no Codex behavior has been observed. Metadata and hook protocol are checked locally |
| `skills-ref validate` | **Not run**: auto mode blocked running it from GitHub. Spec rules are tested locally, and two other validators pass |
| Installed plugin at user scope | **Verified**, one real run, plus the end-to-end suite on Haiku 5.5 |
| No shell, no subagents | **Verified** honest reporting, 2 runs each on Sonnet 5.5 |
| Blind review of the diffs | A model judge ran. **Human review is pending**: see [`evals/BLIND_REVIEW.md`](../evals/BLIND_REVIEW.md) |
| claude.ai, ChatGPT, IDE extensions, Windows, Linux | **Not tested** |

## Gaps in the evaluation

- Eight of the 28 evaluated scenarios are specified but not run, as are the scenarios added after that evaluation, except s40 to s46. Those ran once on Sonnet with no measured benefit, and the plugin arm rarely read the Python references.
- The hidden acceptance tests have gaps: two real regressions passed them until a check was added for those, and others may remain.
