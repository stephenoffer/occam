<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
    <img src="assets/logo-light.png" alt="occam" width="440">
  </picture>
</p>

<h3 align="center">Your coding agent just wrote three classes and a factory that one function call could replace, then told you all the tests pass. Dig deeper, and your whole codebase is either too complex or falls short of what was intended.</h3>

<p align="center">
  Occam is the engineering razor for coding agents.<br>
  Nothing beyond what the requirement needs, and nothing less: it catches the corners your agent cuts, and trims what it overbuilt when you ask.
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

## Nothing beyond

Here's a common problematic agentic behavior example: You ask an agent to create something simple, like a function for determining if a year is a leap year, but you end up with an overengineered mess:

```python
class AbstractLeapYearStrategy(ABC): ...
class GregorianLeapYearStrategy(AbstractLeapYearStrategy): ...
class LeapYearStrategyFactory: ...
class LeapYearCalculator: ...      # with a cache, and options nothing reads
```

But what it needed was just a simple `calendar.isleap(year)`. `occam scan` flags each layer of that, from the abstraction with one implementation to the options nothing reads, and `/occam:razor` cuts what a check shows the change didn't need.

<sub>Written for this page. [The full example, with the real scan output.](docs/examples.md#over-the-top-on-purpose-leap-years-enterprise-edition)</sub>

AI code is getting longer ([duplicated blocks up 81% since 2023](https://www.gitclear.com/write_only_mode_ai_research)) and too often "[almost right](https://survey.stackoverflow.co/2025/ai)", and agents have [deleted failing tests](https://news.ycombinator.com/item?id=46335427) and [a production database](https://oecd.ai/en/incidents/2026-04-27-6153). 

Telling them to be careful doesn't stick: one [Claude Code issue](https://github.com/anthropics/claude-code/issues/17530) finds `CLAUDE.md` ignored in about half of sessions. So occam doesn't ask nicely. It hooks in.

## And nothing less

Another common issue is that an agent will either reward-hack or will not complete a task fully but will report a success.

| The agent | Occam |
|---|---|
| runs `rm -rf ~/` to "clean up" | *this recursively deletes ~/. A person should confirm.* |
| runs `terraform destroy -auto-approve` | *`terraform destroy` is hard to undo. A person should confirm.* |
| deletes `assert refund(100) == 100` to go green | *this change [...] removes 1 assertion. That needs a reason from the intended behavior [...]* |
| says "All tests pass! 🎉" after 3 failed | *A check failed after the last code edit and hasn't passed since.* |
| says "All 47 tests pass." when 12 ran | *no check's output this turn contains that number.* |
| edits anyway after you answered "no" to "Shall I implement it?" | *you asked whether to go ahead with this work, and the user said no, so edits to project files are held for this turn.* |

<sub>Scenarios written for this page; the replies are the real hook's, trimmed.</sub>


## What's different

| | What it does | Measured |
|---|---|---|
| **Hooks, not hope** | Holds an edit, asks you, or sends the agent back, whether or not the model remembers | Every mechanism fired in real runs. Checking after the last edit: 12 of 14 runs → 14 of 14 |
| **The razor** | Asks if code needs to exist, scans for the bloat agents leave, and `/occam:razor` cuts it | On small new Python projects, no: in a preregistered head-to-head on Sonnet it wrote as much as no skill (789 lines against 775) and 44% more than [Ponytail](https://github.com/DietrichGebert/ponytail), whose code also took fewer lines to change later. In repairs it changes far less: about ¼ the code in two large audits. `/occam:razor` has had one smoke run, on an example written for it: 37 lines back to 2, tests passing before and after |
| **Asks you, not itself** | Destructive git, dropped tables, `curl \| sh` and switching occam off wait for a person | Seen live, on a `git stash` over a teammate's work |
| **Checks the report** | Sends the agent back when its report contradicts what ran | Scripted tests only; hasn't fired live |
| **"No" means no** | Answer "no" to "Shall I implement it?" and edits stop for that turn. Fake integrations are flagged as they're written, and an unrequested summary file is held once | Not measured yet |
| **Light** | About 300 tokens of rules; the full playbook only for risky work; `OCCAM_HOOKS=guard` for the safety net alone | Not measured yet |

## The honest part

It hasn't raised pass rates yet: the agent alone already passed nearly every test case. On small new Python projects it lost a preregistered head-to-head to Ponytail: changing occam's code later took 25% more lines, and Ponytail wrote less at about half the cost ([head-to-head](evals/RESULTS.md#head-to-head-with-popular-skills-post-evaluation), 2026-11-08). It costs more, about 34¢ per task on Opus and 12¢ on Sonnet, or 7¢ in a later Sonnet re-run, which is within what chance alone gives. [Every number](docs/evidence.md), and [where occam did worse](docs/examples.md#where-occam-did-worse-an-audit).

## How to use

```bash
claude plugin marketplace add stephenoffer/occam
claude plugin install occam@occam
```

Then keep working. The skills load when there's code to write or review, and the hooks run on their own. Three commands do one job each:

| Type | It does |
|---|---|
| `/occam:razor [path]` | Cuts what the change didn't need, and checks that what it does stays the same |
| `/occam:review [path]` | Reviews the change without editing: what's wrong, what's missing, what it didn't need |
| `/occam:audit [path]` | Audits a codebase or a folder, and fixes things only if you add "and fix" |

`OCCAM_HOOKS=guard` keeps only the safety guards and `OCCAM_HOOKS=off` turns the hooks off. It's a safety net, not a security boundary. The hooks run a local Python script, standard library only, and make no network calls.

It needs Python 3.9 or later. Codex has [its own adapter](adapters/codex) with the hooks, untested there. Other agents can take the skills alone, also untested: `npx skills add stephenoffer/occam --skill '*'`.

[Install options](docs/claude-code.md#install) · [The CLI](docs/tools.md) · [Examples](docs/examples.md) · [Every hook](docs/claude-code.md) · [All docs](docs/README.md) · [MIT](LICENSE)
