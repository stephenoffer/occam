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

Built for Claude Code. The skills also load in Codex, untested there, and the CLI runs anywhere with Python 3.9.

## Nothing beyond

```python
class AbstractLeapYearStrategy(ABC): ...
class GregorianLeapYearStrategy(AbstractLeapYearStrategy): ...
class LeapYearStrategyFactory: ...
class LeapYearCalculator: ...      # with a cache, and options nothing reads
```

```console
$ occam scan calendar_app --min-confidence low
14 findings (0 more below the confidence cut).
  single-impl-abstraction  AbstractLeapYearStrategy has one implementation in this repository.
  pattern-one-product      LeapYearStrategyFactory has 1 public method.
  identical-branches       Both branches of this if do the same thing, so the condition decides nothing.
  unused-option            No call read here passes strategy, enable_cache, verbose to LeapYearCalculator().
  [...]
```

What it needed: `calendar.isleap(year)`.

<sub>Written for this page; the scan output is real, trimmed. [The full example, and another.](docs/examples.md#over-the-top-on-purpose-leap-years-enterprise-edition)</sub>

## And nothing less

| The agent | Occam |
|---|---|
| runs `rm -rf ~/` to "clean up" | *this recursively deletes ~/. A person should confirm.* |
| runs `terraform destroy -auto-approve` | *`terraform destroy` is hard to undo. A person should confirm.* |
| deletes `assert refund(100) == 100` to go green | *this change [...] removes 1 assertion. That needs a reason from the intended behavior [...]* |
| says "All tests pass! 🎉" after 3 failed | *A check failed after the last code edit and hasn't passed since.* |
| says "All 47 tests pass." when 12 ran | *no check's output this turn contains that number.* |

<sub>Scenarios written for this page; the replies are the real hook's, trimmed.</sub>

## Why

AI code is getting longer ([duplicated blocks up 81% since 2023](https://www.gitclear.com/write_only_mode_ai_research)) and too often "[almost right](https://survey.stackoverflow.co/2025/ai)", and agents have [deleted failing tests](https://news.ycombinator.com/item?id=46335427) and [a production database](https://oecd.ai/en/incidents/2026-04-27-6153). Telling them to be careful doesn't stick: one [Claude Code issue](https://github.com/anthropics/claude-code/issues/17530) finds `CLAUDE.md` ignored in about half of sessions. So occam doesn't ask nicely. It hooks in.

## What's different

| | What it does | Measured |
|---|---|---|
| **Hooks, not hope** | Holds an edit, asks you, or sends the agent back, whether or not the model remembers | Every mechanism fired in real runs. Checking after the last edit: 12 of 14 runs → 14 of 14 |
| **The razor** | Asks if code needs to exist, and scans for the bloat agents leave | 0.72× the lines on the Opus holdout, measured afterward; about ¼ the code in two large audits |
| **Asks you, not itself** | Destructive git, dropped tables, `curl \| sh` and switching occam off wait for a person | Seen live, on a `git stash` over a teammate's work |
| **Checks the report** | Sends the agent back when its report contradicts what ran | Scripted tests only; hasn't fired live |
| **Light** | About 300 tokens of rules; the full playbook only for risky work; `OCCAM_HOOKS=guard` for the safety net alone | Not measured yet |

## The honest part

It hasn't raised pass rates yet: the agent alone already passed nearly every test case. It costs more, about 34¢ per task on Opus and 12¢ on Sonnet, or 7¢ in a later Sonnet re-run, which is within what chance alone gives. [Every number](docs/evidence.md), and [where occam did worse](docs/examples.md#where-occam-did-worse-an-audit).

## Use it

Skills load on their own. To call one: `/occam:occam` for code, `/occam:occam-audit` for an audit, `/occam:occam-docs` for docs. It's a safety net, not a security boundary, and `OCCAM_HOOKS=off` switches it off.

[Install options](docs/claude-code.md#install) · [The CLI](docs/tools.md) · [Examples](docs/examples.md) · [Every hook](docs/claude-code.md) · [All docs](docs/README.md) · [MIT](LICENSE)
