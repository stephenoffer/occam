# The `occam` command line

Sixteen commands for auditing code and checking your own changes. Agents reach for them through the skills, and they work just as well from your own terminal.

There's nothing to install. They use only the standard library, need Python 3.9 or later, and behave the same under Claude Code, Codex or a plain terminal.

They don't import or execute the code they scan. `golden`, `mutate`, `bench` and `goal verify` run commands you give them, and anything in `tools` that could run repository code needs `--allow-exec`.

State lives outside the repository, in `~/.cache/occam` or a temporary folder if that isn't writable, so nothing dirties your tree and a repository can't plant it. If nothing is writable, `scan` still works without its cache, while `goal` and `coord` can't run.

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
| Stubs, fake success, invented APIs and packages, duplication, needless abstraction, dead code, bloat, security, masked errors, weak tests, N+1, unbounded work, process-local state, comment noise, naming, reinvented helpers, deprecated APIs, notebooks | `scan`, `rules` | 189 rules. Parsed for Python, text and brace level for others. `--stdin` for a cell, `--diff`, `--new-only`, SARIF output. `rules` lists what it can report |
| Finding your way | `query` | Plain answers about the code, with bounded output: size, commands, entry points, outlines, callers, import graph, what a change reaches, which tests, churn, owners, public API, boundaries. See [Asking questions](#asking-questions) |
| Not using what exists | `query find`, `deps` | Where a name is already defined and called. Is this package real? `--online` checks registries |
| Established analyzers | `tools` | Finds and runs ruff, mypy, semgrep, skylos, eslint, clippy and others, and they outrank occam's own rules |
| Scale | `map`, `partition`, `baseline` | Strategy by size, disjoint shards, agent counts, and a ratchet |
| Behavior and tests | `golden`, `mutate`, `bench` | Prove a refactor changed nothing, show which behavior no test protects, and measure growth |
| Other agents | `coord` | Uncommitted work, worktrees, recent commits, advisory claims |
| Goal-based work | `goal` | Requirements with checks, constraints, scope. Stale evidence and drift are caught |
| Documents against the code | `docs` | Names, paths, flags, links and example syntax in Markdown, checked against the repository, and what a rewrite lost with `--before`. Adds a human-voice linter score if it's installed. See [Checking documents](#checking-documents) |
| Self-critique | `gate` | Blockers across the whole list, new code nothing calls, likely duplicates, weakened tests, and the questions only you can answer. With git, also the change's size, formatting churn, comments lost, what it orphaned even in files it didn't touch, new code out of line with its file, files that nearly always change with these and aren't here, and cited code changing while the design doc doesn't |
| A shared design | `design` | For work that crosses agents or sessions. `design for <path>` gives only what applies to a file, `design check` looks for drift, and `design decide` appends a decision. See [`DESIGN.md`](../DESIGN.md) for occam's own |

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
| `functions [paths] [--sort lines\|complexity\|params]` | The longest and most tangled functions, in Python, Ruby and the braced languages |
| `api [paths] [--base REV]` | Public names by convention. With a base, what was removed, and which signature changes can break a caller, and why |
| `boundaries [paths] [--kind K]` | Where the code meets the outside world and what's at stake: routes, request data, SQL, HTTP calls, file writes, subprocess, environment, money, auth, tenancy, background work. Files where these meet rank first |
| `graph [path]` | With no path, the most depended-on files, cycles and how top-level folders depend on each other. With a path, its imports and importers |
| `impact [paths] [--changed] [--diff BASE]` | What a change reaches, which tests to run, and what names it in text without importing it |
| `tests [paths]` | With no path, what no test reaches and any coverage report left behind. With a path, which tests reach it |
| `history [path] [--since S] [--commits N] [--follow]` | Churn, the files most often fixed, authors, CODEOWNERS, how few people hold most of the commits, and what changes together. Commits by bots aren't counted unless bots are all there is |
| `markers [paths]` | Silenced checkers, skipped and focused tests, hidden failures |
| `leaks [--commits N]` | Credential-shaped lines added on any branch or in any merge, with values withheld, up to the last N commits. If git stops partway, it reports what it read and says where it stopped |

Python and JS or TS imports are traced with workspace packages and `tsconfig` paths, plus Go packages, Java and Kotlin imports, C and C++ local includes, Rust modules, Ruby `require`s and sourced shell files. A test that runs a script as a subprocess counts as reaching it when its code names the file, and the answer labels those. Other languages aren't traced, and answers say so.

Each query answers or exits 2, and a query stops after `--timeout` seconds, 900 by default. A repository's own settings can't change the answer's shape or hide a file, and a query writes nothing into `.git`. If a repository's config says its files are somewhere else, a query refuses to read them. A line that looks like it carries a credential is withheld, going by its shape and by names such as `password` and `token`, so a credential with neither still prints, such as `password: correcthorse` or the short last line of a key. Don't treat these answers as safe to publish because of it. When a repository or user config names filter or diff programs, git older than 2.31 can't switch them off, so that repository is treated as a plain folder.

`entry`, `boundaries` and `functions` name any language in the repository that their patterns weren't written for, because few or none there doesn't mean few or none exist. Ruby's `require` is matched by the shortest path ending in that name, since only the running program knows its load path.

**Limits.** These read text and syntax. Dynamic imports, plugin registration and wiring done in configuration stay invisible, so a name with no references isn't proof it's unused, and `impact` can miss tests. `boundaries` matches common names and libraries, so a custom layer won't show and a word like `balance` can mean something else. `api` goes by convention and can't see who really calls a name. Two agents have tried them, as described below, and no comparison has tested whether they change what an audit finds.

## Very large repositories

`scan`, `map`, `gate`, `deps` and `partition` stop reading after about 75 seconds and say PARTIAL. `--max-seconds N` changes the limit, and 0 removes it. `gate --strict`, and `scan` with `--fail-on`, `--new-only`, `--baseline` or `--format sarif`, have no limit by default, since something else decides on those. `baseline write` reads everything.

If you set a limit on one of those, what went unread counts against it: `scan --fail-on` fails if files in its scope went unread, and `gate --strict` fails if changed files did. A scope read in full can still pass, labeled PARTIAL.

A time-limited command that still can't finish, usually because git is very slow, stops at its limit plus 35 seconds (110 by default), says nothing was checked and exits 2.

Past 50,000 files, `map` is a table of contents, scoped commands read only their scope and say PARTIAL, `partition` needs a folder, and `deps` lists manifests only.

Within those limits, `scan` and `map` read the whole repository to make cross-file rules work, even for one path. Run `occam scan PATH --isolated` or `occam map PATH --isolated` to read only that path, without the rules that need the rest. The cross-file rules left out are dead code, clones, import cycles, phantom local imports and untested modules. `occam tools --run PATH` narrows each analyzer that takes paths.

On 10 million lines of generated code, one run after the limits were added took `map` from 202 s and 4.5 GB to about 6 s, and `gate` from 106 s and 5.2 GB to 4 s and 136 MB.

The first three rows ran once, before the limits, and the rest on 2026-11-06, on a synthetic 3.96 million line repository of copied standard library, with so much other work on the laptop that they read slow (load average about 26):

| Command | Time | Peak memory |
|---|---|---|
| `scan one/folder`, first run | 89 s | 2.3 GB |
| `scan one/folder`, cached | 10 s | 2.2 GB |
| `scan one/folder --isolated` | 0.3 s | 29 MB |
| `query size`, `commands`, `history`, `find`, `grep`, `outline` | 0.5 to 6 s | under 230 MB |
| `query leaks`, reading 61 commits | 22 s | 43 MB |
| `query entry`, `markers`, `boundaries` | 31 to 95 s | under 155 MB |
| `query functions`, first run | 32 s | 316 MB |
| `query graph`, first run, then `impact`, `tests`, cached | 216 s, then 26 to 33 s | under 1 GB |


Two public repositories with real history, on that same loaded laptop, stayed unchanged. On Homebrew/brew (345,000 lines, mostly Ruby, 53,604 commits) every query but `leaks` answered within 24 s and under 150 MB. On Django (543,000 lines, 35,000 commits) they answered within 38 s, peaking at 1.2 GB in `query markers`. `query leaks` read all 53,410 commits that added anything on Homebrew in 261 s and 480 MB on a quieter machine, and 36,104 on Django in 105 s.

`leaks` goes by shape and name, so expect noise. It flagged 390 commit and file pairs on Homebrew. Separately, six plain `git log -G` searches for token shapes found none across that history, so names account for most of these. Confirm each one.

Two agents have used these queries, one on that repository and one on a clone of Django (530,000 lines of Python, 35,000 commits), and what they reported wrong led to the Ruby support above and to fixes in `markers`, `history`, `entry`, `api` and `boundaries`. Afterward the Django agent's blunt advice stood: use `size`, `outline`, `functions`, `find` and `graph`, which were fast and mostly accurate, and check test selection and who owns what by hand. `impact` on a central file reaches nearly every test, because Django's are that connected. Those are two repositories with nothing to compare against, so they don't show that these tools improve an audit.

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

An optional `.occam.json` at the repository root can hold `ignore` (globs) and `disable` (rule ids). A change to it blocks `gate`, so a diff can't clear itself. It holds configuration only, never commands, and anything malformed is dropped. A scan tells you what it ignored because of this file, since the repository controls it.

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

**Limits.** It knows a name appears somewhere in the code, including in a comment, and not whether a document describes it correctly. It doesn't check signatures, defaults or heading anchors, and it parses Markdown only. It runs no example, so run them yourself. Names from other projects and examples about imaginary code come back as leads. All 35 leads on occam's own documents were one of those, and so was the 1 across human-voice's 9. On six audit reports agents wrote, it raised 23 leads in 19,358 words, and none was the agent's mistake: they were library names and names the agents had added in their fixes. It caught the defects planted in a small sample project. On the READMEs of 14 other repositories on one machine, 10 had no leads, and one had 3 links that really were dead, to files since renamed. No agent has used it yet.

## How well it works

It points agents at real bugs. On a real, mostly AI-written 33,000-line billing app, an `undefined-name` lead took an agent straight to a crash: two admin endpoints that raised `NameError` on every call. `occam docs` found 3 dead links in the READMEs of 14 other repositories.

Agents use it, too. In both large audit tests every plugin run ran `scan`, and on the first test plugin runs located the defects the scanner flags more often than no-skill runs did, 63 of a possible 81 against 49.

Most leads are real, and most of the real ones are minor. On seven real repositories it hadn't been tuned on, a blind model judge called 31% of 103 sampled leads worth acting on, 57% true but minor, and 12% false. Getting there took rule fixes that cut critical and high leads on eight other repositories by 67%. That's one model's judgment, on a small sample.

It keeps up with big repositories. Most queries answered within 38 seconds on Django's 543,000 lines, and `scan --isolated` reads one folder of a 4-million-line repository in under a second.

The limits matter as much:

- The scanner alone misses most of what matters. On a blind test, cold, it located about half of the defects a pattern could catch (20 of 41) and under a fifth of those that need semantics (8 of 42), such as a tenant leak. That's why the skill makes reading a required step and treats the scanner as a starting point. With the plugin, agents located as many defects overall as agents without it, not more.
- Python is parsed, and other languages aren't. They get text and brace-level rules, so treat those as weaker.
- The shell rules were read against real scripts, not scored. They were tuned on 296 scripts on one Mac, reading a sample of each rule's hits, and no blind score exists. shellcheck outranks them.
- It has been through adversarial review. A fresh reviewer, on the same model, found three ways the tools could run or break a user's code, after 400 tests written by their author had passed. Those are fixed, with regression tests.

[`evaluation.md`](evaluation.md) has all of this in full, including what has not been checked.
