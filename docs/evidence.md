# What was tested, and what it showed

If you're deciding whether occam is worth installing, start here. The full record, with every table and caveat, is in [`evals/RESULTS.md`](../evals/RESULTS.md). The audit tools have their own write-up in [`evaluation.md`](evaluation.md).

## The short version

**Occam reliably changes how agents work: they check after editing, add regression tests, stop before destructive commands and make fewer unrequested changes. On these test suites that hasn't yet turned into higher pass rates, and it costs more.**

### What it does well

The mechanisms work in real sessions. Every hold in the holdout version fired in real Claude Code runs, and the skill triggered correctly in 22 of 22 checks. A check after the last edit went from 12 of 14 runs to 14 of 14 on the development cases, and with the shell or subagents taken away, agents still reported honestly.

Repairs got more careful. In two large audit-and-repair tests, plugin runs wrote regression tests in every run and added about a quarter of the code, at about 14% lower cost. In the latest, they treated fewer decoys as defects (2 against 10), caused less new damage (10 items against 18) and made fewer unflagged behavior changes (6 against 20). [Auditing and repair](#auditing-and-repair) has the details.

Two leads point toward simpler code. A blind model judge scored skill-arm code as simpler when the run finished, with no difference on whether it would merge it, and human review is still pending. Saved diffs, read after the fact and not preregistered, show plugin runs delivering 0.72 times the source lines of no skill on the Opus holdout and 0.79 on Sonnet. That's three cases, and less code isn't better code by itself. See "Code size from saved runs" in [`evals/RESULTS.md`](../evals/RESULTS.md).

### Where it hasn't helped yet

The cases were almost all within reach of the agent alone before any skill existed, so they could show harm more easily than a gain.

| Holdout, Opus 5.5, 3 cases, 3 runs each | Acceptance | Cost | Hit the time limit |
|---|---:|---:|---:|
| No skill | 9/9 | $5.29 | 0/9 |
| Compact skill | 8/9 | $5.08 | 2/9 |
| Full plugin | 8/9 | $8.32 (+57%) | 2/9 |

- On Sonnet 5.5, the plugin passed 8/9 against 9/9 with no skill. That's one failure in a small sample, and it doesn't establish a cause.
- The Opus failures are silent regressions, one of them wrong arithmetic, in runs stopped at the time limit. The tests first missed them and all three arms scored 9/9. These scores include a check added afterward. No run that finished regressed.
- A fix followed. Rewrites now get a rule to compare old and new, and a hook note. On a fresh case, the plugin and no skill both passed 3/3, and the plugin cost 40% more and took about twice as long. On the case that failed, the plugin passed 3/3 with no timeouts. The samples are small, the no-skill runs on the fresh case made the same comparison unprompted, and machine load and other changes can't be ruled out, so this doesn't show the fix was the reason.
- The Python guidance showed no measured benefit on seven new Sonnet cases, at about 23% more cost per run, and the new references were read in only 1 of 21 plugin runs. Direct pointers to them, tested afterward on five of those cases, didn't change that: 1 of 15. A later case on moved APIs and sinks tied at 3/3, at about 35% more cost per run.
- In the audits, plugin runs located as many defects as no skill and fixed fewer, a median of 48.5 of 60 serious ones against 55.
- On hard cases, the plugin passed 3 of 9 runs against 4 of 9 with no skill. Both are below.

### What it costs, and what that pays for

The full plugin cost 57% more than no skill on the Opus holdout and 85% more on Sonnet, with about twice the turns. In dollars, that's about 34 cents more per task on Opus and 12 cents on Sonnet. The largest single item is the fresh-context review of high-consequence changes, at about $0.21 to $0.26 per reviewed run on Opus and $0.08 on Sonnet. Where no reviewer runs, most of the extra is the guidance itself in context, not extra turns, and a held edit costs at most 3.5% of a run. The audit tests were the exception, at about 14% less over both, though runs took about 1.8 times as long.

### What's next

Install the full plugin for its enforcement. A benefit on harder or larger work is possible, and this suite can't establish one, so a preregistered study on eight new repositories, scoring cleanup, decisions and harm, has begun. See [`evaluation.md`](evaluation.md) for its status.

## Hard cases

**No sign of a benefit, at more cost.** A preregistered round on 8 fresh cases stopped at its pilot because no skill passed 5 of them, so it says nothing about the plugin. An exploratory look at the other 3 on Sonnet 5.5, not a round, had the plugin passing 3 of 9 runs against 4 of 9 with no skill, at 64% more cost and twice the turns. A blind audit afterward found one check unfair to the plugin, and setting it aside gives 4 of 9 each, which doesn't change the reading. The look also exposed a real defect: a hook send-back could replace a good report with a short reply to a note the reader never sees. The closing text of those send-backs now asks for the whole report again, and no agent has run that yet. See "Hard cases" in [`evals/RESULTS.md`](../evals/RESULTS.md).

## Auditing and repair

**More careful repairs, not more of them.** Across two large tests of about 28,000 lines, 3 runs per arm each, every plugin run used `scan` and wrote regression tests. Plugin runs added about a quarter of the code and cost about 14% less over both tests, while taking about 1.8 times as long. In the latest test they reported fewer decoys as defects (2 against 10), caused less new damage (10 items against 18) and made fewer unflagged behavior changes (6 against 20).

They didn't find or fix more. The plugin located 92.8 of 122 per run against 93.0, and fixed a median of 48.5 of 60 serious defects against 55; totals of 293 and 294 of 360 look level only because one no-skill run fixed 19. In the latest test it fixed 50.0 of 60 against 57.3, and left 22 open against 4. An earlier test on a 3,000-line repository also found no benefit. The blind judge's "fixed" calls held up: executable checks written afterward agreed on 348 of 354, and the judge was right in all 6 disagreements. These tests have design problems, including a prompt telling agents not to change behavior while scoring fixes that do, which `evaluation.md` lists.

**The scanner on real code.** On seven real repositories it hadn't been tuned on, mostly AI-written, a blind model judge called 31% of 103 sampled leads worth acting on, 57% true but minor, and 12% false. Getting there took rule fixes that cut critical and high leads on eight other repositories by 67%, so earlier scanner numbers from synthetic code overstated its precision. One agent then audited a real 33,000-line billing app with the skill: the scanner led it to a real crash bug, but the audit was too shallow, stopping after 76 seconds with billing logic unread. [`evaluation.md`](evaluation.md) has the details.

## What each combination has been through

Unless a row says otherwise, this describes the plugin at hash `ee947fc74a0dc453`. Anything added to `plugin/` after that, including `skills/occam/scripts/`, `skills/occam-audit/`, the `occam-python` references, the hook's Python handling, the failure-mode checks, the wording and checks from the Karpathy and Ponytail review and the shared design doc, was built by other sessions. It has been through at most the small re-evaluation at hash `6e9b898640b2ac71`, not the holdout comparison, and later changes haven't been through either. See the change log in [`evals/PREREGISTRATION.md`](../evals/PREREGISTRATION.md).

| Combination | Status |
|---|---|
| Claude Code 2.1.318 with the plugin: end to end, smoke, holdout | **Verified** on real runs, with Opus 5.5 and Sonnet 5.5 |
| Re-evaluation at `6e9b898640b2ac71`: one fresh case, and two holdout cases again | **Run** on Opus 5.5, 7 plugin runs and 3 no-skill runs. See [`evals/RESULTS.md`](../evals/RESULTS.md) |
| `marketplace add` and `install` | **Verified** in a throwaway config: installs and lists 9 skills, 1 agent, 8 hook events. The plugin has since grown to 11 skills, 2 agents and 9 hook events |
| Plain copy into `.claude/skills/` | **Verified** discovery of all 9 skills that existed then, one run |
| Enforcement hook logic | **Verified** by the free test suite. On a clean export at `2475ede2a1bd683d`, Python 3.14 passed 4,799 with 1 skipped, and the stock macOS Python 3.9 passed 4,784 with 15 skipped and one timeout under load that passed alone |
| Failure-mode checks | **Verified** by deterministic tests on cases we wrote, in `tests/test_failure_modes.py`. **Partly seen** in real runs (holds, person-confirm asks, failed-check note). The web denial and a Stop comparison sending an agent back have **not** been seen, and their effect alone isn't measured. The rule on changes right after a failed check was narrowed after these runs, using their traces |
| `occam docs`, the `occam-docs` skill and the human-voice handoff | **Verified** by the free tests in `tests/test_docs_tool.py`, and by hand against the real human-voice linter at 0.1.0 and 0.9.0 on one small sample project. Run on 20 existing documents and six saved audit reports, where its 59 leads were all explainable, and on the READMEs of 14 other repositories, where it caught 3 links that really were dead. **Not run** on an agent: no evidence yet that agents use it or that their documents improve. It adds about 100 always-on tokens per session |
| Rule card, `OCCAM_HOOKS=guard`, self-review default and subagent card, added 2026-11-06 | **Not run** on an agent. Free tests in `tests/test_lean_core.py`, and a replay of 73 saved runs through the old and new hooks, where the only change was 11 reviewer send-backs becoming self-review send-backs in the same runs. The replay can't show the card's effect, because those runs loaded the skill before editing. Every result above measured the old behavior: a skill hold on any edit past a small one, and the reviewer agent on every high-consequence file |
| Codex | **Not run**: dropped for now, so no Codex behavior has been observed. Metadata and hook protocol are checked locally |
| `skills-ref validate` | **Not run**: auto mode blocked running it from GitHub. Spec rules are tested locally, and two other validators pass |
| Installed plugin at user scope | **Verified**, one real run, plus the end-to-end suite on Haiku 5.5 |
| No shell, no subagents | **Verified** honest reporting, 2 runs each on Sonnet 5.5 |
| Blind review of the diffs | A model judge ran. **Human review is pending**: see [`evals/BLIND_REVIEW.md`](../evals/BLIND_REVIEW.md) |
| claude.ai, ChatGPT, IDE extensions, Windows, Linux | **Not tested** |

## Gaps in the evaluation

- Eight of the 28 evaluated scenarios are specified but not run, as are the scenarios added after that evaluation, except s40 to s46. Those ran once on Sonnet with no measured benefit, and the plugin arm rarely read the Python references.
- The hidden acceptance tests have gaps: two real regressions passed them until a check was added for those, and others may remain.
