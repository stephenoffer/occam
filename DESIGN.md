# Design: occam

Owner: the maintainer. Not yet verified against a commit.

Where this file and the code disagree about what exists, the code is right: say so and fix this file. Accepted decisions stand until a later one supersedes them. Anyone can propose, and the owner accepts. Keep it short, with no code, schemas, task lists or tour of the repository: [`docs/README.md`](docs/README.md) is the map.

## Problem

Coding agents skip what doesn't show in a demo: finishing the work, stating what they didn't check, leaving other people's changes alone. People adopting them need that caught without paying more for it than it saves. Occam has no measured quality benefit yet, and per-case comparisons made after the fact put its plugin runs at 1.24 to 1.94 times the cost of no skill, so what's worth spending here is limited. On the one holdout where that cost was split, extra turns looked like more of it than words.

## Non-goals

- A security boundary. Hooks fail open, and deny rules and sandboxes do that job.
- A planner or spec system in the core skill: no phases, task trees or prescribed steps. `occam goal` tracks requirements and can run the commands that prove them, and prescribes no steps.
- Fewest lines. Less code that isn't complete doesn't count.
- Replacing established analyzers. `occam tools` runs them first, and they outrank occam's rules where they overlap.
- Claiming a benefit no preregistered run has shown.

## Success

A comparison with criteria fixed in advance shows better work than no skill at a cost worth paying. Until then the README keeps saying there's no measured benefit.

## Current design

- Skills in `plugin/skills/` are portable text. The core is `plugin/skills/occam/SKILL.md`, with references loaded when relevant.
- Hooks in `plugin/hooks/` keep the important parts from being skipped. `plugin/hooks/codex_hook.py` is a smaller set for Codex, and hasn't been run under Codex.
- Tools in `plugin/skills/occam/scripts/occam_tools/` are standard library only, need Python 3.9, and keep their state outside the repository.
- Agents in `plugin/agents/` review and audit. They have no edit tools, though Bash can write, so staying read-only is an instruction.
- Evals in `evals/` compare arms by hash, with hidden checks and frozen fixtures.

## Planned

- Confirming CI passes. `.github/workflows/ci.yml` is written, and no one has recorded here whether it has passed.

## Contracts

- A skill may only name `occam` commands that exist in `plugin/skills/occam/scripts/occam_tools/cli.py`. `tests/test_package.py` checks the core skill, the audit skill and its references, and the docs skill.
- `plugin/skills/occam/scripts/occam_tools/files.py` and `plugin/skills/occam/scripts/occam.sh` keep identical git safety settings. `tests/test_occam_sh.py` enforces it.
- `evals/hidden_support.py` is copied alone into the sandbox, so it can't import anything else.
- Hook notes reach `plugin/skills/occam/scripts/occam_tools/` only through modules that fail silently, such as `plugin/hooks/scan_notes.py` and `plugin/hooks/design_notes.py`.

## Open questions

- Is the plugin's cost worth what it buys? The owner decides, from a paid comparison.
- Should a paid test of the design doc run before more is built on it? The owner decides.

## Decisions

Append only, with `occam design decide`. To change one, supersede it.

- 2026-11-05 core-word-budget [accepted] The core skill stays at or under 2,000 words, so every addition is paid for by a cut. Why: instruction-cost evidence in docs/research.md, and no raising the cap to fit text. Applies: `plugin/skills/occam/SKILL.md`, `tests/test_package.py`.
- 2026-11-05 no-new-send-backs [accepted] New checks warn inside `gate` or as a one-time note, and don't add holds or send-backs. Why: on the Opus holdout plugin runs made about 18 API calls against 10, and turns look like more of the cost than words. Applies: `plugin/hooks/occam_hook.py`, `plugin/skills/occam/scripts/occam_tools/surgical.py`, `plugin/skills/occam/scripts/occam_tools/design.py`.
- 2026-11-05 scope-notes-must-be-true [accepted] A scope note says nothing unless the syntax tree, the source reader or git history shows it, never from text that merely looks alike. Why: a fresh reviewer showed text comparison calling meaningful changes formatting. Applies: `plugin/skills/occam/scripts/occam_tools/surgical.py`.
- 2026-11-05 silent-when-unseen [accepted] The rule claiming nothing passes an option stays silent if any call could be out of sight. Why: agents act on findings, and a false claim costs more than a miss. Applies: `plugin/skills/occam/scripts/occam_tools/project.py`.
- 2026-11-05 wording-is-ours [accepted] Ideas from other projects are credited in docs/research.md, and their wording isn't copied. Why: that record states no text is copied, and one source's license is unclear. Applies: `docs/research.md`, `plugin/skills/`.
- 2026-11-05 evals-log-changes [accepted] Any change under plugin/ after a measured hash gets an entry saying no result covers it. Why: results describe a hash, and a claim has to match what ran. Applies: `evals/PREREGISTRATION.md`, `evals/RESULTS.md`.
- 2026-11-05 grader-stays-separate [accepted] `evals/grade_workspaces.py` doesn't import the hook it grades, even where that means a second copy of a pattern, such as `CLAIMS_PASSING`. Why: a shared bug would pass both sides. Applies: `evals/grade_workspaces.py`.
- 2026-11-05 design-doc-stays-small [accepted] A session gets a pointer to this file, an edit gets the decisions on that file, and the code wins on what exists. Why: agents followed a stale instruction file in 90.1% of choices, one sentence moved that to 91.4% following the code, and Gloaguen et al. found context files gave no improvement in task success at over 20% more inference cost. Applies: `plugin/skills/occam/scripts/occam_tools/design.py`, `plugin/hooks/design_notes.py`.
- 2026-11-06 design-tool-reads-little [accepted] occam design compares only Current design, Contracts and Applies with the code, takes files and folders rather than patterns, and lists what it can't tell apart as not checked. Why: three fresh reviews kept finding false notes wherever it interpreted free-form Markdown, and a wrong note is worse than none. Applies: `plugin/skills/occam/scripts/occam_tools/design.py`.
- 2026-11-06 hard-to-undo-list-grows [proposed] The list of commands a person confirms grows to destroying or resetting through cloud CLIs, Docker, Prisma and Rails, recursive deletes of root or home on Windows, and SQL DELETE or UPDATE with no WHERE, superseding no-new-send-backs for these destructive commands only. New Stop wording for stopping short stays inside the existing check. Why: The costliest incidents in docs/large-codebase-failures.md began with one of these run on a guess. A replay of 1,870 distinct saved agent commands asked no new times. Landed on a labeled self-review; the independent review is pending. Applies: `plugin/hooks/occam_evidence.py`, `plugin/hooks/unfinished.py`.
- 2026-11-06 confirm-irreversible-commands [accepted] A person confirms destroying or resetting through cloud CLIs, Docker, Prisma and Rails, recursive deletes of root or home on Windows, and SQL DELETE or UPDATE with no WHERE. For these destructive commands only, this supersedes no-new-send-backs. New Stop wording for stopping short stays inside the existing check. Why: Accepted by the owner on 2026-11-06. The costliest incidents in docs/large-codebase-failures.md began with one of these run on a guess, and a replay of 1,870 saved agent commands asked no new times. Applies: `plugin/hooks/occam_evidence.py`, `plugin/hooks/unfinished.py`. Supersedes: `hard-to-undo-list-grows`.
- 2026-11-06 user-refusal-and-report-holds [proposed] Two holds, for these cases only superseding no-new-send-backs. A bare no to a final message asking to do the work holds edits for that turn, like review-only. A new upper-case report file such as FIX_REPORT.md that the request didn't ask for is held once per path. The three fake-integration scanner rules stay within no-new-send-backs: a note on edit, never a send-back. Why: The no hold enforces the user's explicit word, so it can't fire in an unattended run, and a Hacker News thread on agents ignoring it drew 1,563 points. A replay of 82 saved runs changed no hold, ask or send-back, and no saved run wrote a report-named file. Two fresh reviews found 8 defects, all fixed with tests. Landed proposed, for the owner to accept or reject. Applies: `plugin/hooks/occam_hook.py`, `plugin/hooks/codex_hook.py`, `plugin/hooks/classify.py`.
- 2026-11-07 catalog-500-owner-calls [accepted] For the 500-item quality catalog: a person confirms rm -rf of a variable path that isn't a temp folder, running a file the same command downloaded, and pg_restore --clean or mongorestore --drop, superseding no-new-send-backs for these forms only. Stop-time claims (secure with no scan or review, done with unverified goal items, Go or C concurrency with no race run, servers left running) are added only to a send-back that already happens. unsafe-deserialize covers Java, Ruby and PHP and blocks gate as Python's does, and ci-unpinned-action flags third-party actions pinned to a tag. Rows no static check can reach count as done with their guidance. A person also confirms reading a credential file into the agent's context, before the read. Why: Accepted by the owner on 2026-11-07, answering occam-97's questions with the recommended option for asks, Stop items and out-of-reach rows, and choosing blocking for the gate rules. Applies: `plugin/hooks/occam_evidence.py`, `plugin/hooks/stop_checks.py`, `plugin/skills/occam/scripts/occam_tools/rules_text.py`, `plugin/skills/occam/scripts/occam_tools/rules_config.py`, `docs/quality-catalog.md`.
