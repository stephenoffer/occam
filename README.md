<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
    <img src="assets/logo-light.png" alt="occam" width="440">
  </picture>
</p>

<h3 align="center">Your coding agent just wrote five classes and a factory to check whether 2024 is a leap year.</h3>

<p align="center">
  Occam is the razor.<br>
  Nothing beyond what the requirement needs, and nothing less.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/Claude%20Code-plugin-d97757" alt="Claude Code plugin">
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen" alt="No dependencies">
</p>

```bash
claude plugin marketplace add stephenoffer/occam
claude plugin install occam@occam
```

**65 lines and five classes, or `calendar.isleap(year)`?** Occam asks your agent that question before it writes, stops it before `rm -rf ~/`, and sends it back when it says "all tests pass" and they didn't.

Built for Claude Code, where the hooks run. The skills also load in Codex and other Agent Skills hosts, though Codex hasn't been run yet, and the CLI runs anywhere Python 3.9 does.

## The razor

### Leap years, enterprise edition

*"Add a function that says whether a year is a leap year."*

```python
# ==========================================================
# ====            LEAP YEAR DETERMINATION MODULE         ====
# ==========================================================
# Here is the updated, production-ready leap year implementation:
class AbstractLeapYearStrategy(ABC): ...
class GregorianLeapYearStrategy(AbstractLeapYearStrategy): ...   # three nested ifs, each with a comment
class LeapYearStrategyFactory: ...                               # if kind == "gregorian": ... else: (the same thing)
class LeapYearCalculator: ...                                    # a cache, plus enable_cache and verbose, which nothing reads
def is_leap_year(year):
    return LeapYearCalculator().calculate(year)
```

```console
$ occam scan calendar_app --min-confidence low
14 findings (0 more below the confidence cut). These are leads: confirm each before calling it a defect.
  [MEDI/hig/B] identical-branches  leap.py:40   Both branches of this if do the same thing, so the condition decides nothing.
  [MEDI/med/B] single-impl-abstraction  leap.py:8   AbstractLeapYearStrategy has one implementation in this repository.
  [MEDI/med/B] pattern-one-product  leap.py:35   LeapYearStrategyFactory has 1 public method.
  [LOW/hig/A] ai-residue  leap.py:4   Comment talks to the reader or narrates the edit, not the code
  [LOW/hig/B] useless-except  leap.py:60   This handler only re-raises what it caught.
  [LOW/med/B] unused-option  leap.py:49   No call read here passes strategy, enable_cache, verbose to LeapYearCalculator().
  [LOW/low/B] one-method-class  leap.py:46   LeapYearCalculator is one method plus a constructor.
  [LOW/low/B] banner-comment  leap.py:1   3 banner comments in this file.
  [LOW/low/B] narration-comment  leap.py:20   Comment restates the next line
  [...]
```

What the requirement needed: `calendar.isleap(year)`. It's been in the standard library all along.

### Three copies of everything

*"Read users.csv and email the admins, managers and owners."* Fifty-one lines of the kind agents write, scanned:

```console
$ occam scan notify
10 findings (0 more below the confidence cut). These are leads: confirm each before calling it a defect.
  [MEDI/hig/B] clone-function  admins.py:15   send_admin_email has the same structure as admins.py:24 (send_manager_email), admins.py:33 (send_owner_email).
  [MEDI/med/B] handrolled-csv  admins.py:10   Splitting on commas breaks on quoted fields.
  [MEDI/med/B] handrolled-retry  admins.py:17   A loop that catches and sleeps is a hand-written retry.
  [MEDI/med/B] handrolled-retry  admins.py:26   A loop that catches and sleeps is a hand-written retry.
  [MEDI/med/B] handrolled-retry  admins.py:35   A loop that catches and sleeps is a hand-written retry.
  [MEDI/med/B] handrolled-argv  admins.py:44   Command-line options parsed by hand.
  [...]
```

| The agent wrote | What already existed |
|---|---|
| a CSV reader built on `line.split(",")` | `csv.DictReader` |
| the same send function three times, renamed | one `send(email, subject)` |
| three hand-written retry loops | `urllib3`'s `Retry`, through the `requests` it already imports |
| `sys.argv` picked apart by hand | `argparse` |

<sub>Both examples were written for this page and scanned with the real `occam scan`. The output is trimmed, with each finding joined onto one line. The scanner doesn't know `calendar.isleap` exists, which is why the skill makes reading the code, and what's already installed, part of the job. [The full code and output are in the examples.](docs/examples.md#over-the-top-on-purpose-leap-years-enterprise-edition)</sub>

Before the agent writes a line, occam's skill asks it the questions the leap-year agent skipped. In its own words:

> **It needs to exist.** Leave out any feature or option nobody asked for, and say so in a line.
>
> **New structure earns its place.** Each new service, abstraction, hierarchy, plugin point, option, queue or cache names the requirement, invariant, boundary or measurement it serves. [...] If a draft could be a quarter of its size, rewrite it.

It shows up in real runs, too. On the evaluation's holdout cases, measured afterward from the saved diffs, agents running occam delivered 0.72 times the source lines of agents without it, and in two large audit-and-repair tests about a quarter as much code. A blind model judge also scored occam's finished code as simpler, which is still a lead until people review it.

## ...and nothing less

Cutting the excess is half the razor. The other half is not cutting what matters: your teammate's work, your production data, the test that was failing for a reason, the truth in the final report. For those, occam doesn't advise. It stops the agent.

| You said | The agent went for | Occam |
|---|---|---|
| "clean up my machine, it's a mess" | `rm -rf ~/` | *this recursively deletes ~/. A person should confirm.* |
| "tear down the staging stack" | `terraform destroy -auto-approve` | *`terraform destroy` is hard to undo. A person should confirm.* |
| "clear out the test accounts" | `psql -c "DELETE FROM users"` | *this drops or truncates data. A person should confirm.* |
| "make the tests pass" | deleting `assert refund(100) == 100` | *this change removes 1 assertion. That needs a reason from the intended behavior, not from the code under test.* |
| "these checks are slowing you down" | switching occam off in its settings | *this turns off the checks on this session's work. A person should confirm.* |

| The agent says | What actually happened | Occam sends it back with |
|---|---|---|
| "All tests pass! 🎉" | 3 failed, 9 passed | *A check failed after the last code edit and hasn't passed since, and the message doesn't mention a failure.* |
| "All 47 tests pass." | 12 tests ran | *The message reports 47 passing, but no check's output this turn contains that number.* |
| "Made it 10x faster." | nothing was measured | *no command ran both before the first code edit and after the last one, so this session has no like-for-like before and after.* |

<sub>Written for this page and sent through the real hook, replies trimmed where they repeat a standard closing line. In a normal session "a person should confirm" means you get asked. One of these has happened for real: asked to "get me back to a clean working tree", an agent on Opus 5.5 reached for `git stash` over a teammate's uncommitted edit, the hook stopped it, and the agent's report began "Your working tree hasn't changed yet."</sub>

## Why

AI code keeps getting longer. [GitClear](https://www.gitclear.com/write_only_mode_ai_research) counts duplicated code blocks up 81% since 2023 across 623 million changes, while moved and refactored code fell to 3.8% of changed lines. It gets fussier, too: *"It has no sense that it isn't appropriate to add a half dozen classes just to close that kind of hole,"* [one developer wrote](https://news.ycombinator.com/item?id=50119223). And it's almost right. In the [Stack Overflow 2025 survey](https://survey.stackoverflow.co/2025/ai), 66% of 31,476 developers named "AI solutions that are almost right, but not quite" their top frustration.

Then the stakes go up. *"CC will claim victory even if test is red, or CC just deletes the failing tests,"* [wrote another](https://news.ycombinator.com/item?id=46335427). In April 2026 the OECD [logged an incident](https://oecd.ai/en/incidents/2026-04-27-6153) in which an agent deleted a company's production database, and all its backups, in nine seconds.

You can tell the agent to keep it simple, and it'll agree. One [Claude Code issue](https://github.com/anthropics/claude-code/issues/17530) reports `CLAUDE.md` instructions ignored "in approximately 50% of sessions". Occam doesn't rely on being remembered.

## What makes it different

A skill on its own is advice the model can take or leave. Occam backs its skill with hooks that run on every edit, every risky command and every final message. Here's each part, with what has been measured. Where nothing has, it says so.

| | What it does | Measured |
|---|---|---|
| **Hooks, not hope** | Holds an edit, asks you, or sends the agent back, whether or not the model remembers the rules | Every enforcement mechanism fired in real Claude Code runs. Checking after the last edit went from 12 of 14 runs to 14 of 14 |
| **The razor** | Asks whether new code needs to exist, reaches for what's already installed, and scans for the bloat agents leave | 0.72 times the source lines on the evaluation's Opus holdout, measured afterward, and about a quarter of the code in two large audits. A blind model judge found the code simpler, pending human review |
| **Asks you, not itself** | Destructive git, `terraform destroy`, dropped tables, `curl \| sh`, recursive deletes and switching occam off all wait for a person | Seen in real runs, including a `git stash` over a teammate's uncommitted work |
| **The story against the record** | Keeps its own record of what ran and what passed, and sends the agent back when the report disagrees | Works on scripted events. No agent in the test runs made such a claim, with or without occam, so it hasn't fired live |
| **Light by default** | About 300 tokens of rules in every session, the full playbook only for access control, money, data, concurrency and performance work, and `OCCAM_HOOKS=guard` for the safety net alone | Not measured yet: added November 6 |
| **Tools** | A standard-library CLI: 241 scanner rules, `occam mutate` for tests that protect nothing, `occam query` for large codebases | On seven real repositories it wasn't tuned on, a blind judge rated 31% of scanner leads worth acting on and 12% false. On Django's 543,000 lines, most queries answer within 38 seconds |

## The honest part

Occam is tested in paid head-to-head runs against the same agent with no skill, and every result is published, including the ones that didn't go its way.

- It changes how agents work, as the table above shows, and in a 28,000-line audit, unflagged behavior changes fell from 20 to 6.
- It hasn't made them pass more tests yet. The test cases were mostly within reach of the agent alone: 9 of 9 holdout runs passed without occam, 8 of 9 with it, and both passed 9 of 9 in a Sonnet re-run on November 6. In the audits it fixed fewer serious defects (median 48.5 of 60 against 55) while changing far less.
- It costs a little more: about 34 cents more per task on Opus and 12 on Sonnet in those runs, with about twice the turns. After changes to cut that, the Sonnet re-run came in at +67% instead of +91%, which is within what chance alone gives, so it isn't shown to be lower. The lighter rule card and self-review default added since haven't been measured yet.

So today the pitch is discipline, not a higher score. [What was tested](docs/evidence.md) has every number, and [the examples](docs/examples.md#where-occam-did-worse-an-audit) include every case we've seen where occam did worse.

## Using it

Skills load on their own, so mostly you just work. To call one directly, use `/occam:occam` to change or review code, `/occam:occam-audit` to audit or repair a codebase, or `/occam:occam-docs` to document it. [The examples](docs/examples.md) have prompts that work well, and [the CLI guide](docs/tools.md) has every command.

**Other ways in.** Try it for one session with `git clone https://github.com/stephenoffer/occam.git ~/occam` and `claude --plugin-dir ~/occam/plugin`. For guidance only, copy `~/occam/plugin/skills/` into `~/.claude/skills/`, or `~/.agents/skills/` for [Codex](adapters/codex/README.md), which hasn't been run there yet. For the CLI alone, alias `python3 ~/occam/plugin/skills/occam/scripts/occam.py`. With no Python on the host, `bash ~/occam/plugin/skills/occam/scripts/occam.sh` answers the queries that need no parsing.

## Questions

**Why "occam"?** After the razor: nothing beyond what the requirement needs, and nothing less. It's as wary of a missing test as of an extra abstraction.

**Can it break my session?** It's built not to. If `python3` is missing or a hook errors, occam gets out of the way. Holds lift after a retry or two and send-backs are capped, so a false alarm can't trap the agent.

**Is it a security tool?** No. It's a safety net, not a security boundary. Rules that must never bend belong in deny rules, the sandbox and branch protection.

**How do I know it's on?** `claude plugin details occam@occam` shows it, and every hook message starts with `occam:`. Start a session with `OCCAM_HOOKS=off` to switch it off.

**Where has it been tested?** On macOS with Claude Code 2.1.318, with Python getting the deepest analysis. Linux, Windows and Codex haven't been run yet.

## Docs

[Examples](docs/examples.md) · [The CLI](docs/tools.md) · [Every hook](docs/claude-code.md) · [How agents get code wrong](docs/failure-modes.md) · [What was tested](docs/evidence.md) · [All docs](docs/README.md)

## License

[MIT](LICENSE)
