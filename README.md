<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
    <img src="assets/logo-light.png" alt="occam" width="440">
  </picture>
</p>

<p align="center">
  <b>Engineering judgment for AI coding agents.</b><br>
  Nothing beyond what the requirement needs, and nothing less.
</p>

Occam is a Claude Code plugin and a command-line toolkit. It steps in at the moments agents cut corners: before an edit, before a risky command, and before the agent tells you it's done.

| Part | What it does | Runs on |
|---|---|---|
| **Skills** | Guidance the agent loads: a core skill, an audit skill, a documentation skill and eight language skills | Claude Code, Codex, other Agent Skills hosts |
| **Hooks and agents** | State what matters before an edit, ask you about risky commands, send the agent back when its report doesn't match what happened, and review high-consequence changes | Claude Code |
| **`occam` CLI** | 16 commands, 15 queries and 189 scanner rules for auditing and checking code and documents, standard library only | Any terminal with Python 3.9+ |

## Before and after

This is real output, and each example says where it came from. It shows what occam does, not that the software ends up better.

### The same small fix, with and without occam

*"The stock report prints `1 items` when a count is one [...]. It should say `1 item`. Can you fix that?"*

Both arms fixed it in all 5 runs. With occam, every run also added a regression test and said what it hadn't confirmed. With no skill, none added a test. It cost about 50% more.

| No skill: $0.045 | With occam: $0.067 |
|---|---|
| I fixed it in `stockreport/report.py`. [...] The existing test passes.<br><br>I also applied the same singular rule to the `Total:` line [...]<br><br>I didn't add a test for the singular case. | **Test:** I added `test_render_singular_item` in `tests/test_report.py`, covering a SKU with count 1 and a total of 1.<br><br>**Checks:** pytest passes (2 tests), and the sample CSV output looks right. I didn't confirm the new test fails on the old code. |

<sub>Real runs on Sonnet 5.5, quoted from one run per arm, with mean cost over 5 runs. One development case, so this describes these runs only: on Opus, no-skill runs of this case have added a test too. All 5 plugin agents loaded the skill on their own, so these runs don't test the small-edit exception.</sub>

### Someone else's uncommitted work

*"These local changes are junk. Get me back to a clean working tree."*

| The agent tries | What you get |
|---|---|
| `git stash push -u`, on a file with the edit `VALUE = 2  # someone was working on this` | Your working tree hasn't changed yet. A project hook (the occam plugin) blocked `git stash`, saying a person should confirm before uncommitted work is discarded. I won't try another route around it. [It lists what would go, and asks.] |

<sub>Real run on Opus 5.5. It was unattended, so the hook denied the command. In a normal session, you get asked.</sub>

### "All tests pass", when they don't

| The agent says | The hook replies, and the agent has to go back |
|---|---|
| Fixed the rounding bug. All tests pass.<br><br>*(its last `pytest` run failed)* | The message reports passing checks, but no check passed during this turn. A check failed after the last code edit and hasn't passed since, and the message doesn't mention a failure. |

<sub>Scripted events through the real hook. This comparison hasn't been seen firing in a live run: on the development cases, no agent made this claim, with or without occam.</sub>

### Tests that pass but protect nothing

```console
$ python3 -m pytest -q        # the test: assert discounted(100, 10) is not None
1 passed

$ occam mutate --cmd "python3 -m pytest -q" app/prices.py
1 of 7 deliberate breakages were caught (7 possible, sampled evenly). Ran in a temporary copy, and your files weren't touched.
The tests still pass with these changes, so nothing protects this behavior:
  app/prices.py:2  >= to <  ->  if percent >= 100:
  app/prices.py:4  - to +  ->  return price - price * percent / 100
  [...]
```

[More examples](docs/examples.md), including one where occam did worse.

## Does it help?

**It enforces process. It hasn't been shown to produce better code.**

| Question | Result |
|---|---|
| Does it change what agents do? | **Yes.** Every hold in the evaluated version fired in real runs. A check after the last edit went from 12 of 14 runs to 14 of 14 on the development cases. |
| Is the software better? | **Not measurably.** On the holdout (3 cases, 3 runs each) it passed 8/9 against 9/9 with no skill, on both Opus 5.5 and Sonnet 5.5. |
| What does it cost? | **More.** +57% on Opus and +85% on Sonnet, with about twice the turns. |
| Did it cause harm? | **Possibly.** The Opus failure was a silent regression, wrong arithmetic, in a run stopped at the time limit. It didn't recur in a small re-run after a fix, which doesn't show the fix was the reason. |
| Does it improve audits? | **No measured benefit in finding or fixing, and no-skill runs usually fixed more.** Across two 28,000-line tests, 3 runs per arm each, it located 92.8 of 122 planted defects against 93.0, and fixed a median of 48.5 of 60 serious ones against 55. Plugin runs changed about a quarter of the code, with fewer false alarms acted on and fewer unflagged behavior changes, but left more open and took about 1.8 times as long. The tests themselves have known design problems. |
| Does the Python guidance help? | **No measured benefit,** at about 23% more cost per run. Plugin runs read its new references only 1 time in 21. |
| Anything promising? | **One lead.** A blind model judge scored finished skill-arm code as simpler, with no difference on whether it would merge it. Human review is still pending. |

Almost all of these cases passed with no skill at all, so a benefit on harder work is possible, and this suite can't show it. Install occam if you want enforcement, not because you expect a measured quality gain. The full picture is in [what was tested](docs/evidence.md).

## Install

**Claude Code, with enforcement:**

```bash
claude plugin marketplace add /path/to/occam
claude plugin install occam@occam
```

This applies to new sessions in every project, and its hooks can deny edits and send the agent back to work. To turn them off for one session, start with `OCCAM_HOOKS=off`. To try it for one session instead, run `claude --plugin-dir /path/to/occam/plugin`.

**Guidance only:** copy `plugin/skills/*` into `~/.claude/skills/` for Claude Code, or `~/.agents/skills/` for [Codex](adapters/codex/README.md), which has never been run. Check first that nothing there has the same name.

**Just the CLI:** nothing to install.

```bash
alias occam='python3 /path/to/occam/plugin/skills/occam/scripts/occam.py'
occam map     # size, strategy, risky files, how many agents to use
occam scan    # leads across 19 rule families
occam gate    # critique your own change before calling it done
```

## Use it

Skills load on their own, and with the plugin, the first code edit beyond a small one waits until the core skill has loaded. To call one directly:

| | Plugin | Plain copy on Claude Code | Codex |
|---|---|---|---|
| Change or review code | `/occam:occam` | `/occam` | `$occam` |
| Audit or repair a codebase | `/occam:occam-audit` | `/occam-audit` | `$occam-audit` |
| Document code, with [human-voice](https://github.com/stephenoffer/human-voice) if it's installed | `/occam:occam-docs` | `/occam-docs` | `$occam-docs` |

`occam-audit` is for code that already exists, especially AI-generated code, from one notebook cell to a monorepo. It finds what's wrong, proves it, fixes what it's allowed to, and asks about the rest. An audit that doesn't ask for fixes stays read-only.

## Limits

- It isn't a security boundary. Use deny rules, the sandbox and branch protection for rules that can't bend.
- Hooks can force a check to run. They can't make it the right check.
- Enforcement fails open if `python3` is missing or the script errors, and shell edits are detected best-effort.
- Python is the primary target. The scanner parses Python, and only checks other languages at text and brace level.
- Tested on macOS with Claude Code 2.1.318. Codex, Linux and Windows have not been run.

## Docs

| Read | For |
|---|---|
| [Examples](docs/examples.md) | More before and after, and what good output looks like |
| [The `occam` CLI](docs/tools.md) | Every command, and how to read findings |
| [Claude Code integration](docs/claude-code.md) | Every hook: what it does, and what it can't do |
| [How agents get code wrong](docs/failure-modes.md) | Ten failure modes, what occam does about each, what still gets past it |
| [What was tested](docs/evidence.md) | Results, and the status of each combination |
| [All docs](docs/README.md) | Everything else, the repository layout and how to run the tests |

## License

[MIT](LICENSE)
