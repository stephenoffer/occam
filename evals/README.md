# Evaluation suite

For maintainers. None of this is loaded during coding sessions. Results are in `RESULTS.md`, and decisions fixed in advance are in `PREREGISTRATION.md`.

## Free checks

```bash
python3 -m pytest tests/ -q     # about 9 minutes, mostly the scale fixtures
python3 evals/freeze.py check   # have the cases moved since the freeze?
python3 evals/replay_hook.py    # what would this hook do on the saved runs? About 10 seconds. Needs evals/results/
python3 evals/cost_report.py LABEL   # where a saved eval's money went, by part, and what a 5-minute cache would change
python3 evals/rule_power.py     # how often a round's decision rule would be wrong, and the margin to use
```

The replay counts holds and send-backs by reason, split by whether the run passed, so it catches a false hold or a needless send-back before a paid run does. Point `--hooks` at an older copy to compare. It shows what fires, not that it helps, because the recorded agent carries on regardless.

These cover package lint, scenario completeness, leak checks, the enforcement hook driven through full event sequences, and fixture calibration: for each case the starter fails, the reference passes, and each trap fails for the intended reason. They prove the checks can detect defects, not that the skill helps.

## Agent comparisons

These are real, billed model runs. You need Claude Code 2.1.269 or later. `run_eval.sh` and `audit_comparison.py` set `CLAUDE_CODE_PROMPT_CACHE_TTL=5m` for both arms unless you override it, because the subscription default of 1 hour costs more and these runs rarely pause for 5 minutes.

```bash
# run_eval.sh LABEL SUITE VARIANT ABLATION RUNS MAX_COST_USD [CASE_GLOB] [extra flags]
evals/run_eval.sh e2e e2e plugin none 1 4                     # does every part fire for real?
evals/run_eval.sh smoke smoke plugin with-without 1 12
evals/run_eval.sh holdout holdout plugin with-without 3 12
evals/run_eval.sh compact holdout compact none 3 5
EVAL_MODEL=claude-sonnet-5-5 evals/run_eval.sh holdout-sonnet holdout plugin with-without 3 4
python3 evals/summarize.py --label plugin=evals/results/holdout/graded/graded.json
```

**Variants:** `plugin` is everything a Claude Code user installs, `portable` is the skills alone, `compact` is a short core with no references, language skills or hooks, and `empty` is nothing at all, for pilots.

Trigger accuracy doesn't use hidden checks. Stage the suite with `evals/stage.py --suite triggers --variant plugin --out DIR`, run `claude plugin eval DIR --scaffold --runs 1 --ablation none --no-publish --trust-plugin --allow-tools Bash Write Edit --output-dir OUT`, then `python3 evals/summarize.py --triggers OUT/aggregate-result.json`.

How it works:

1. `stage.py` builds a temporary plugin root holding the chosen variant and each case's prompt and graders. `hidden/` and `solutions/` stay behind, so the agent can't reach them.
2. `claude plugin eval` runs each case in an isolated home and workspace, with and without the skill, on identical starting repositories and limits. `--keep-temp` retains each workspace.
3. `grade_workspaces.py` runs the evaluator-owned checks on a copy of each workspace under `sandbox-exec`, because this executes agent-written code. It refuses to run if there is no sandbox. It then deletes the retained run directories.
4. `summarize.py` reports raw counts, with no significance claims. `--blind-out DIR` writes anonymized diffs and reports for human review, plus a key to open after scoring.

Every paid step is logged in `results/ledger.jsonl`. Raw results are gitignored and can include whole transcripts.

## Layout of a case

| Path | Purpose | Agent can see it? |
|---|---|---|
| `prompt.md` | Task as a person would type it, plus run limits | Yes, as the prompt |
| `files/`, `place-files.sh` | Starting repository | Yes, as the workspace |
| `graders/` | Skill-fired indicator and `*-diag-*` diagnostics. Not acceptance. | No |
| `hidden/` | Acceptance checks | No |
| `solutions/` | Calibration only | No |

## Reading results

- **Smoke is development data** used to revise the skill. Only the holdout is a clean comparison.
- **Acceptance** is one pass/fail per run per case. Everything else is a diagnostic.
- **Most cases clear without the skill.** They can detect harm and cost, but they can show little benefit even if some exists. That limit comes from these fixtures and this model, and it's the first thing a new case should try to address.
- **End-to-end cases** check that each mechanism fires in real Claude Code, by reading the trace. They say nothing about whether that improves the software.
- **A Codex run** is a discovery and basic-behavior check, not a comparison. See `codex_smoke.py`.

## Machine-specific notes

Paths and sandbox behavior are from macOS. `/usr/bin/git` fails under the eval's Bash sandbox on macOS, so `stage.py` adds a note naming the real binary to both arms. Grading uses `sandbox-exec`, so on Linux, run it inside a disposable container and adapt `sandbox_profile`.
