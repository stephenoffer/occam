# Claude Code integration

A skill on its own is guidance: the model reads it and decides. The Claude Code docs say so directly, and recommend hooks for anything that must happen every time. The `occam` plugin adds that deterministic layer.

Checked against the official docs on 2026-11-05 and Claude Code 2.1.318. `evals/RESULTS.md` records what was actually run.

## Install

```bash
claude plugin marketplace add /path/to/occam
claude plugin install occam@occam
```

This adds 11 skills, 2 agents and 8 hook events. `claude plugin details occam@occam` shows the inventory and estimated token cost. It takes effect in your next session.

To try it for one session without installing anything:

```bash
claude --plugin-dir /path/to/occam/plugin
```

**What you are opting into:** the default install is at user scope, so it applies to new sessions in every project. A marketplace added from a local path is read in place, so edits to `plugin/` go live in new sessions, with no version step. The hooks can deny edits and send the agent back to work. They run a Python script on your machine on each edit, shell command and read. To remove them, run `claude plugin uninstall occam@occam`. To turn them off for one session, start Claude Code with `OCCAM_HOOKS=off`.

If you want the guidance with no enforcement, copy `plugin/skills/*` into `~/.claude/skills/` or `<repo>/.claude/skills/` instead. Check first that nothing there has the same name.

## What fires, and how

Each part acts with one of these levels of firmness:

| Term | Means |
|---|---|
| **Denied** | The tool call is refused, and that doesn't give way |
| **Held** | The tool call is denied, with a reason the model can act on. *Held once* lets a retry through |
| **A person confirms** | You're asked. In an unattended run nobody can answer, so it is denied |
| **Sent back** | When the agent stops, it's told to continue. Each complaint is sent back once per state of the code, at most 5 times without a check passing. `/goal` continuing a turn doesn't silence it. |
| **Noted** or **mentioned** | A line of context is added, and nothing is stopped |

### Held

From the shell, only the destructive actions named on this page stop a command. It's a list, not a judgment, so a destructive command it doesn't name gets through, such as `rm app.py`, `find . -delete` or `git reset HEAD~3`. These rows apply to edit tools unless they name the shell.

| Part | Fires when | Lifts when |
|---|---|---|
| `occam:occam` core skill | Before the first code edit in a session made with an edit tool, unless it's small: under 20 lines and 1,500 characters, in an ordinary source file, within 3 code edits and 2 files, with nothing consequential in the request, the path or the text. A small edit gets small mode's rules stated instead. This is best effort, and the rule is stated beside the edit. It hasn't been shown to help: the only runs where it fired, on one case with an earlier wording, passed 0 of 2 on Sonnet against 2 of 2 with no skill. With the current wording that case passed 5 of 5, but every agent loaded the skill on its own, so the exception didn't fire | The skill is loaded |
| Read-only requests | The prompt says review-only, plan-only, "don't change anything" and similar. Edits to project files are denied for that turn, including by subagents. From the shell, that means any write except one plain command naming a path that isn't there yet. Only writes the hook can see count, so `find -delete` or `xargs rm` gets through | Plain words like "go ahead", or a person approving a plan or answering a question |
| Weakened checks | A test edit removes assertions or adds a skip, or a test file is deleted from the shell. Right after a failed check, with no code changed since: check configuration changes or a new suppression in an existing file | Held once, and the report must then name it |

### A person confirms

A subagent has nobody to ask, and a question it can't get answered leaves it waiting for good, so there these are denied with a reason it can report.

| Part | Fires when |
|---|---|
| Destructive git | `reset --hard`, `stash`, `restore`, `checkout --`, `clean -f`, `rebase`, `push --force`, `branch -D`, `commit --amend`, always. A plain commit and staging aren't stopped, on any turn |
| Hard-to-undo commands | Turning these hooks off in settings, recursive deletes of the root, home, the whole working directory or absolute paths outside temp, a download run straight in a shell, `terraform destroy`, `kubectl delete`, and drops through a SQL client |
| Credentials | A credential shape in `curl` or `wget` arguments. In a web request it is **denied** and doesn't give way, and in a new edit it is **held once**. Values are never repeated |

### Sent back

Each complaint is sent back once per state of the code, at most 5 times without a check passing, and a pass starts that count again. `/goal` continuing a turn doesn't silence it.

| Part | Fires when |
|---|---|
| A check after editing | The agent stops, having edited code with no check since |
| Honest pass claims | The final message claims passing checks, but none passed this turn. Failures, empty runs and fully skipped runs in a check's output don't count as passing, even when a pipe hides the exit status |
| Honest final message | A check failed after the last edit, hasn't passed since and goes unmentioned, a test count appears in no output, a measured speedup has no before and after from one command, a result varied with nothing changed, or an install, deletion, manifest or check config goes unnamed. These are all sent back at the same time |
| Finishing the request | The final message admits part of the request wasn't done, or a notebook this turn changed can't run top to bottom. Each fires once. Passes on a report that doesn't say so, and on what a static read of the notebook can't see |
| Reading the final diff | The agent is already being sent back for another reason, having changed several files with no diff since |
| `occam:code-reviewer` agent | The agent stops, having changed a high-consequence file with no finished review since the last edit. It can say it did a self-review instead. After an earlier review this turn, it can be a review of only what changed since, if that one finished and covered the whole diff |
| Scan at stop | The agent stops with findings from "Scan on edit" still present. It can say why they're fine |
| Audit check at stop | An audit session stops with serious leads still raised in files it changed, new or not. It has to fix them or say they remain, so a report can't call them fixed unchecked |

### Noted or mentioned

| Part | Fires when |
|---|---|
| Review and plan requests | The prompt reads as review or planning. Noted in context, along with `occam:occam-python` when the prompt involves Python, since no edit exists to hold |
| What `references/security.md` says most needs saying | The file path or request involves auth, tenancy, money, migrations, webhooks and similar. Stated once, before the edit, with the path to the rest |
| What `references/performance.md` says most needs saying | The request states speed, scale or memory needs, or a workload of 1,000 or more. Stated once, before the edit |
| What `references/design.md` says most needs saying | A dependency manifest is edited, or the request is a dependency decision. Stated once, before the edit |
| Language skills | The first edit in a language |
| `references/verification.md` | The first test file edit |
| `references/collaboration.md` | The first subagent |
| Very large source files | An edit touches, or leaves, a source file over 1,000 lines, generated files, notebooks and SQL aside. Mentioned once per file, before the edit if it is already that large. Splitting stays a separate decision |
| Python facts | The code being written contains a known trap, such as `subprocess.run` without `check=`, including through a shell redirect or inline script; a new module named after a standard library one; the first notebook or test edit; a request to audit or split Python, or about a notebook. The fact itself is stated, at most three per edit and each once per session, with a path to more. Nothing is held, and code with no known trap adds nothing |
| Large rewrites | An edit replaces 30 or more lines of existing source code. Noted once per session that comparing old and new on the same inputs is what shows its behavior survived |
| Review before the report | The first edit to a high-consequence file. Noted once that the review comes once checks pass and before the report, so the report isn't written twice |
| A copy run beside a real one | A failing command ran both a copy of the old code and this code's check. Noted once to run this code's check alone before reporting |
| A run of failed checks | Three in a row, after code changed. Noted once per streak |
| Pushback | A prompt disputes a result after edits or checks |
| Files that steer later sessions | The first edit to `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, a memory directory or similar. Noted once |
| After compaction | The conversation is compacted. Noted that loading the skill restores it, and names a recorded goal |
| Long runs | At 30 code edits or 10 files. Noted once how to record a goal |
| Scan on edit | An edit introduces a serious finding, such as a stub, an invented import or a secret. Only what this work added, each one once. A clean edit costs no tokens |
| Documentation skill | The prompt asks for documentation, or a document is edited. Once per session, and not after `occam:occam-docs` has loaded. Files that steer agents don't count. Claude Code only |
| Audit skill | The prompt reads as an audit. An audit that doesn't ask for a fix is read-only, like "review only" |
| Design doc | Once per file for each agent, when an edit touches a file that an accepted decision in `DESIGN.md` applies to. A repository with no design doc pays nothing |

## What this can't do

Being clear about this matters more than the table above.

- **It can't make the work good.** Hooks can force a check to run. They can't make it the right check, or make the fix correct.
- **Loading isn't following.** The hook can make sure the skill was loaded. Whether each rule is applied is still the model's judgment.
- **Shell edits are detected best-effort.** The hook parses the command line and catches redirects, `sed -i`, `tee`, `cp`, `mv`, `rm`, formatters with write flags, installers that change a manifest, and Python heredocs that write files. Formatters are recognized through `python -m`, `uv run`, `uvx`, `poetry run`, `conda run`, `nbqa` and similar. A dry run such as `black --check` is neither an edit nor a check, because formatting says nothing about behavior. A tool that writes because of its configuration, such as Ruff with `fix = true`, can't be seen from the command line. Behind a pipe, a failure is recognized only from what the output says. When Claude Code reports `bashEditDiff`, it uses that too. A file written by a project script or an unusual command can be missed, and so can git commands hidden behind an alias, a script or complex substitution.
- **A check is recognized by its command,** so anything that looks like running tests or code counts. The hook doesn't judge whether it was relevant.
- **Read-only detection is a pattern on the prompt's wording.** It can miss an unusual phrasing, or occasionally hold when it shouldn't. It doesn't give way on its own, since the agent reports and stops rather than looping. The reason it gives says how to lift it.
- **It fails open.** If `python3` is missing or the script errors, nothing is enforced. A broken hook shouldn't wedge your session, and that is the tradeoff.
- **It gives way.** A hold lifts after two retries of the same edit, and each complaint at Stop is sent back once per state of the code, at most 5 times without a check passing, so a false positive can't trap the agent. The agent is told to mention any unmet hold in its report.
- **Subagents skip the load hold,** because the coordinating agent answers for their work. The read-only and destructive git guards still apply, and their edits still count at Stop.
- **The final-message checks only run in a turn that edited code, and they read wording.** They compare patterns in the message with what was recorded, so a claim worded differently isn't seen and a name mentioned in passing counts as reported. [`failure-modes.md`](failure-modes.md) lists the ways around each one.
- **It is not a security boundary.** A determined or misdirected agent can get around it. Use deny rules, the sandbox and branch protection for rules that can't bend.

## Cost

Enforcement costs turns and tokens, and the evaluation measures it: see `evals/RESULTS.md`. The always-on cost was about 695 tokens per session at the evaluated hash, from skill descriptions. `claude plugin details occam@occam` shows the current figure, which was about 1,250 on 2026-11-05. On 2026-11-06, after the descriptions were shortened, it reported about 1,200 always on, about 4,300 for the core skill, and about 1,800 for `occam-python`, with other language skills at 500 to 950. The reviewer agent is the largest single cost, which is why it only applies to high-consequence files.

Billed by the token, `CLAUDE_CODE_PROMPT_CACHE_TTL=5m` repriced saved runs 14 to 22% lower, with no gap over 5 minutes in any of them. That lowers the cost with or without occam, so it doesn't change the comparison, and a session with long pauses would pay to write its context again.

## Sharp edges worth knowing

- **Worktree isolation may hide your diff.** A subagent with `isolation: worktree` branches from your default branch, not your HEAD, so a reviewer there won't see uncommitted work. That's why `code-reviewer` doesn't set it.
- **The reviewer isn't strictly read-only.** It has no edit tools, and its brief forbids changes, but `Bash` can still write and subagents inherit a permissive session mode.
- **A fresh reviewer helps because it hasn't seen your reasoning.** Handing it your conclusions removes that. Same-model reviewers aren't statistically independent, and approval is a claim to inspect, not proof.
- **Plugin agents ignore `hooks`, `mcpServers` and `permissionMode` in their frontmatter.**

## Adding a project-specific check

The plugin has no way to know your project's commands, and won't read them from repository content. To run a check of your own when the agent stops, add a Stop hook to your own settings. Give it a fast check, leave expensive suites to CI, and stop it looping, since a blocking Stop hook runs again when the turn continues.

`claude plugin eval` loads a plugin's hooks, so the end-to-end cases in `evals/cases/e2e/` run against all of this for real. To check your own install, see `evals/README.md`.
