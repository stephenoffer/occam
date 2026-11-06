# The `occam` command line

Tools for auditing code and checking your own changes. Agents use them through the skills, and you can run them yourself.

There's nothing to install. They use only the standard library, need Python 3.9 or later, and work the same under Claude Code, Codex or a plain terminal.

They don't import or execute the code they scan. `golden`, `mutate`, `bench` and `goal verify` run commands you give them, and anything in `tools` that could run repository code needs `--allow-exec`.

State lives outside the repository, in `~/.cache/occam` or a temporary folder if that isn't writable, so nothing dirties your tree and a repository can't plant it. If nothing is writable, `scan` still works without its cache, while the ledger, `goal` and `coord` can't run.

```bash
alias occam='python3 /path/to/occam/plugin/skills/occam/scripts/occam.py'

occam map     # size, strategy, risky files, layers, how many agents
occam scan    # leads across 19 rule families. Output is bounded
occam query   # plain answers: who calls this, what a change reaches, who owns it
occam gate    # critique your own change before calling it done
```

## Commands

| Problem | Tool | What it does |
|---|---|---|
| Stubs, fake success, invented APIs and packages, duplication, needless abstraction, dead code, bloat, security, masked errors, weak tests, N+1, unbounded work, process-local state, comment noise, naming, reinvented helpers, deprecated APIs, notebooks | `scan`, `rules` | 179 rules. Parsed for Python, text and brace level for others. `--stdin` for a cell, `--diff`, `--new-only`, SARIF output. `rules` lists what it can report |
| Finding your way | `query` | Plain answers about the code, with bounded output: size, commands, entry points, outlines, callers, import graph, what a change reaches, which tests, churn, owners, public API, boundaries. See [Asking questions](#asking-questions) |
| Not using what exists | `reuse`, `deps` | What's already in the repository, the standard library and your dependencies. Is this package real? `--online` checks registries |
| Established analyzers | `tools` | Finds and runs ruff, mypy, semgrep, skylos, eslint, clippy and others, and they outrank occam's own rules |
| Scale | `map`, `partition`, `baseline`, `ledger` | Strategy by size, disjoint shards, agent counts, a ratchet, and a ledger shared safely by concurrent agents |
| Safe repair | `fix` | Python only and deliberately narrow: by default, only brief comments that are plainly an assistant talking, proven to change no code. Dry run by default. Import removal is opt-in, because it can't be proven safe |
| Behavior and tests | `golden`, `mutate`, `bench` | Prove a refactor changed nothing, show which behavior no test protects, and measure growth |
| Other agents | `coord` | Uncommitted work, worktrees, recent commits, advisory claims |
| Goal-based work | `goal` | Requirements with checks, constraints, scope. Stale evidence and drift are caught |
| Documents against the code | `docs` | Names, paths, flags, links and example syntax in Markdown, checked against the repository, and what a rewrite lost with `--before`. Adds a human-voice linter score if it's installed. See [Checking documents](#checking-documents) |
| Self-critique | `gate` | Blockers across the whole list, new code nothing calls, likely duplicates, weakened tests, and the questions only you can answer. With git, also the change's size, formatting churn, comments lost, what it orphaned even in files it didn't touch, and new code out of line with its file |
| Deferred work | `debt` | Lists marked shortcuts and TODOs from comments, and flags the ones that never say when they come due |

## Asking questions

`scan` judges code. `query` answers plain questions about it, and every query reads only, runs nothing from the repository, and bounds what it prints with `--top`. `--format json` gives the same answer as data.

| Query | Answers |
|---|---|
| `size [paths] [--depth N]` | Lines and files by language and directory, each subsystem with a manifest, and the largest files |
| `commands` | The build, test and lint commands in Makefiles, `package.json`, `pyproject.toml`, tox, nox, CI files and READMEs, labeled when inferred. Runs none |
| `entry [paths]` | Installed commands, mains, HTTP routes, background jobs, CLI parsers, container commands |
| `outline FILE...` | Classes and functions with line ranges, signatures and complexity, so you can read one part of a large file |
| `find NAME [paths]` | Where a name is defined, imported, called (and from which function), used by tests, named in strings, and mentioned in comments and docs |
| `grep REGEX [paths] [--in code\|comment\|string] [--lang L]` | A search that knows code from comments and strings |
| `functions [paths] [--sort lines\|complexity\|params]` | The longest and most tangled functions |
| `api [paths] [--base REV]` | Public names by convention. With a base, what was removed, and which signature changes can break a caller, and why |
| `boundaries [paths] [--kind K]` | Where the code meets the outside world and what's at stake: routes, request data, SQL, HTTP calls, file writes, subprocess, environment, money, auth, tenancy, background work. Files where these meet rank first |
| `graph [path]` | With no path, the most depended-on files, cycles and how top-level folders depend on each other. With a path, its imports and importers |
| `impact [paths] [--changed] [--diff BASE]` | What a change reaches, which tests to run, and what names it in text without importing it |
| `tests [paths]` | With no path, what no test reaches and any coverage report left behind. With a path, which tests reach it |
| `history [path] [--since S] [--commits N] [--follow]` | Churn, fix commits, authors, CODEOWNERS, how few people hold most of the commits, and what changes together |
| `markers [paths]` | Silenced checkers, skipped and focused tests, hidden failures |
| `leaks [--commits N]` | Credential-shaped lines ever added in history, with values withheld |

Python and JS or TS imports are traced with workspace packages and `tsconfig` paths, plus Go packages, Java and Kotlin imports, C and C++ local includes, Rust modules and sourced shell files. A test that runs a script as a subprocess counts as reaching it when it names the file. Other languages aren't traced, and answers say so.

**Limits.** These read text and syntax. Dynamic imports, plugin registration and wiring done in configuration stay invisible, so a name with no references isn't proof it's unused, and `impact` can miss tests. `boundaries` matches common names and libraries, so a custom layer won't show and a word like `balance` can mean something else. `api` goes by convention and can't see who really calls a name. No agent has used these yet, so nothing here shows that they change what an audit finds.

### With no Python

`scripts/occam.sh` answers the queries that need no parsing, with bash and git alone: `size`, `find`, `grep`, `history`, `leaks`, `markers`, `tests`, `commands`, `entry`, and `shell`, which runs `bash -n` over every script and looks for common defects. It keeps the same promises and switches off the same git settings as `occam.py`, and a test fails if the two lists differ. It works on bash 3.2, so stock macOS is fine. It can't tell a comment from a use, and it has no `outline`, `functions`, `api`, `boundaries`, `graph` or `impact`.

```bash
bash /path/to/occam/plugin/skills/occam/scripts/occam.sh size
bash /path/to/occam/plugin/skills/occam/scripts/occam.sh find handle_payment
```

## Very large repositories

`scan` and `map` read the whole repository to make cross-file rules work, even for one path. Run `occam scan PATH --isolated` or `occam map PATH --isolated` to read only that path, without the rules that need the rest. The cross-file rules left out are dead code, clones, import cycles, phantom local imports and untested modules. `occam tools --run PATH` narrows each analyzer that takes paths.

These ran once on a synthetic 3.97 million line repository of copied standard library, on a laptop other work was also using:

| Command | Time | Peak memory |
|---|---|---|
| `scan one/folder`, first run | 89 s | 2.3 GB |
| `scan one/folder`, cached | 10 s | 2.2 GB |
| `scan one/folder --isolated` | 0.3 s | 29 MB |
| `query size`, `commands`, `history`, `find`, `grep`, `outline` | 0.2 to 2 s | under 60 MB |
| `query leaks`, reading 61 commits | 10 s | 28 MB |
| `query entry`, `markers`, `boundaries` | 16 to 51 s | under 130 MB |
| `query functions`, cached | 2 s | 355 MB |
| `query graph`, `impact`, `tests`, cached | 12 s | 1.1 GB |
| `occam.sh size`, `find`, `grep`, `history`, `tests`, `commands`, `shell` | under 2 s | under 20 MB |
| `occam.sh entry`, `markers`, `leaks` | 9 to 24 s | under 30 MB |

The queries that say "cached" need a first scan's worth of reading, about 89 s here, if nothing has scanned this repository yet.

## Reading findings

A finding such as `[CRIT/hig/B] sql-injection  payments.py:19` gives its severity, its confidence and its tier.

| Tier | Means | What an agent may do |
|---|---|---|
| **A** | Mechanical | Fix it |
| **B** | Needs a check | Fix it, with a check that shows the fix works |
| **C** | Needs a person | Ask first |

Findings are **leads, not defects**. Confirm each one before calling it a defect. Expect many on any large repository: Python's standard library, used as a control, gets about 3,600 at all confidences, mostly complexity and duplication, which are true of that code and don't make it defective.

## What it looks like

These ran on a 20-line sample, [shown in the examples](examples.md#code-that-looks-finished).

```console
$ occam scan payments.py
occam scan 2.0.0: 1 of 1 files, 20 lines, 0.06s. python 1.
7 findings (1 more below the confidence cut). These are leads: confirm each before calling it a defect.
[...]
  [CRIT/hig/B] sql-injection  payments.py:19
      db.execute() receives SQL built from runtime values.
  [HIGH/hig/C] stub-body  payments.py:13
      refund has no body.
  [MEDI/hig/B] missing-timeout  payments.py:7
      requests.post() waits forever by default.
[...]
Tier: A mechanical, B fix with a check, C ask first.
```

```console
$ occam gate payments.py
occam gate: 1 changed files, 0 deleted, 2 blockers, 7 warnings.

FAIL  Implementation is complete
  ! payments.py:13  stub-body: refund has no body.
  - payments.py:14  placeholder-comment: Comment admits the code is a placeholder
FAIL  Security
  ! payments.py:19  sql-injection: db.execute() receives SQL built from runtime values.
[...]
Checks only you can make:
  ? Reread the original request. Is every part of it done, connected and reachable through the real entry point?
  ? Did you honor every constraint the user stated, including ones from earlier in the conversation?
[...]
NOT READY: fix these, or escalate each with a reason.
```

## Configuring it

An optional `.occam.json` at the repository root can hold `ignore` (globs) and `disable` (rule ids). It holds configuration only, never commands, and anything malformed is dropped. A scan tells you what it ignored because of this file, since the repository controls it.

```json
{ "ignore": ["evals/cases", "evals/fixtures"] }
```

To silence one finding, add a comment on its line such as `# occam: ignore[query-in-loop] a handful of ids`, naming the rule and the reason. A scan reports how many findings were silenced this way.

## Checking documents

`occam docs` reads Markdown and reports where it disagrees with the repository. With no paths it checks the documents changed in git.

```bash
occam docs README.md docs/
occam docs README.md --before /tmp/README.before.md   # what a rewrite lost or added
occam docs guide.md --register tutorial               # the genre to give the linter
```

It reports:

- an identifier, dotted name, call or flag in inline code that appears nowhere in the code
- a path that doesn't exist, and a relative link that doesn't resolve from the document
- in shell examples, a script or module of this project that doesn't exist, and a flag of one of this project's commands that appears nowhere
- in Python examples, a syntax error, or an import nothing here mentions, and JSON that doesn't parse

`--before` lists each number, inline code span, link and code block that a rewrite lost or added. It compares presence, so saying something twice and then once isn't a change. The exit status is 1 on any lead, change, broken linter or unreadable document, and 2 when nothing was checked. `occam gate` also lists leads for changed documents, as warnings.

**human-voice.** Prose belongs to [human-voice](https://github.com/stephenoffer/human-voice), a separate, optional install, and the `occam-docs` skill hands drafts to it. When `occam docs` finds its linter, each document gets a score, and the score never changes the exit status. Without it the output says the voice check didn't run. It looks in the repository's skill folders first, which needs `--allow-exec` because running a copy there runs repository code, then in Claude Code plugin installs, newest first, then in the user-level skill folders human-voice's installer writes to. Versions 0.1.0 and 0.9.0 both work, but their scores use different scales, and only newer versions have bands and the `tutorial` and `release_notes` registers.

**Limits.** It knows a name appears somewhere in the code, including in a comment, and not whether a document describes it correctly. It doesn't check signatures, defaults or heading anchors, and it parses Markdown only. It runs no example, so run them yourself. Names from other projects and examples about imaginary code come back as leads. All 35 leads on occam's own documents were one of those, and so was the 1 across human-voice's 9. On six audit reports agents wrote, it raised 23 leads in 19,358 words, and none was the agent's mistake: they were library names and names the agents had added in their fixes. It caught the defects planted in a small sample project, but it hasn't yet caught a real mistake in a real document, and no agent has used it.

## How far to trust it

- **The scanner alone misses most of what matters.** On a blind test, cold, it located about half of the defects a pattern could catch (20 of 41) and under a fifth of those that need semantics (8 of 42), such as a tenant leak. That's why the skill makes reading a required step and treats the scanner as a starting point.
- **Most leads are true but minor.** On seven real repositories it hadn't been tuned on, a blind model judge called 31% of 103 sampled leads worth acting on, 57% true but minor, and 12% false. That's one model's judgment, on a small sample.
- **Agents with the plugin did no better.** No plugin run in the one head-to-head ran `scan`, so that test says nothing about the scanner, and no comparison has tested these tools on code too large to read whole.
- **Shell rules were read against real scripts, not scored.** They were tuned on 296 scripts on one Mac, reading a sample of each rule's hits, and no blind score exists. shellcheck outranks them.
- **Python is parsed, other languages aren't.** Other languages get text and brace-level rules, so treat them as weak.
- **It has been wrong before.** A fresh reviewer, on the same model, found three ways the tools could run or break a user's code, after 400 tests written by their author had passed. Those are fixed, with regression tests.

[`evaluation.md`](evaluation.md) has all of this in full, including what has not been checked.
