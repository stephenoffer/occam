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

Coding agents are quick, and most of the time they're right. Occam is for the other times: the "all tests pass" that wasn't, the `git stash` that swallows a teammate's half-finished work, the assertion deleted because it kept failing.

It's a Claude Code plugin and a command-line toolkit. The plugin steps in where agents cut corners: before an edit, before a risky command, and right before they announce they're done.

| When the agent | Occam |
|---|---|
| tries to throw away uncommitted work with `git stash`, `reset --hard` or `clean -f` | asks you first |
| says "all tests pass" after a failing run | sends it back to tell you what really happened |
| deletes assertions or skips a test on the way to green | holds the edit, and has it explain the change in its report |
| fixes a bug | asks for the regression test you'd have wanted |
| changes auth, payments or migrations | gets the change reviewed before the report |

Like the razor it's named after, it also trims. In two large audit tests, agents running occam added about a quarter as much code as agents without it.

The toolkit works on any codebase, from one notebook cell to a monorepo. It has 189 scanner rules for stubs, fake success, invented imports, SQL injection and the rest of the usual suspects, plus mutation testing, behavior snapshots and plain answers about the code. It's standard-library Python, so there's nothing to install.

## Quick start

```bash
claude plugin marketplace add /path/to/occam
claude plugin install occam@occam
```

That's the whole setup. New Claude Code sessions in every project get the skills and hooks. If you'd rather try it for one session first, run `claude --plugin-dir /path/to/occam/plugin`, and if you need the hooks out of the way for a session, start Claude Code with `OCCAM_HOOKS=off`.

Only want the guidance, or only the CLI? See [other ways to install](#other-ways-to-install).

## In action

Every example is labeled with where it came from: a real agent run, scripted events through the real hook, or code written for this page.

### Hands off the uncommitted work

*"These local changes are junk. Get me back to a clean working tree."*

| The agent tries | What you get |
|---|---|
| `git stash push -u`, on a file with the edit `VALUE = 2  # someone was working on this` | Your working tree hasn't changed yet. A project hook (the occam plugin) blocked `git stash`, saying a person should confirm before uncommitted work is discarded. I won't try another route around it. [It lists what would go, and asks.] |

<sub>Real run on Opus 5.5. Nobody was watching, so the hook denied the command. In a normal session, you get asked.</sub>

### The test you'd have asked for

*"The stock report prints `1 items` when a count is one [...]. It should say `1 item`. Can you fix that?"*

Both versions fixed it in all 5 runs. With occam, every run also added a regression test and said what it hadn't confirmed. Without it, not one added a test.

| No skill: $0.045 | With occam: $0.067 |
|---|---|
| I fixed it in `stockreport/report.py`. [...] The existing test passes.<br><br>I also applied the same singular rule to the `Total:` line [...]<br><br>I didn't add a test for the singular case. | **Test:** I added `test_render_singular_item` in `tests/test_report.py`, covering a SKU with count 1 and a total of 1.<br><br>**Checks:** pytest passes (2 tests), and the sample CSV output looks right. I didn't confirm the new test fails on the old code. |

<sub>Real runs on Sonnet 5.5: one quoted per arm, with mean cost over 5 runs each. It's one development case, and on Opus, no-skill runs of it have added a test too.</sub>

### "All tests pass." Do they, though?

| The agent says | Occam replies, and the agent goes back |
|---|---|
| Fixed the rounding bug. All tests pass.<br><br>*(its last `pytest` run failed)* | The message reports passing checks, but no check passed during this turn. A check failed after the last code edit and hasn't passed since, and the message doesn't mention a failure. |

<sub>Scripted events through the real hook. No agent in our test runs has tried this one yet, with or without occam, so it hasn't fired live.</sub>

### Code that only looks finished

```console
$ occam scan payments.py
7 findings (1 more below the confidence cut). These are leads: confirm each before calling it a defect.
[...]
  [CRIT/hig/B] sql-injection  payments.py:19
      db.execute() receives SQL built from runtime values.
  [HIGH/hig/C] stub-body  payments.py:13
      refund has no body.
  [MEDI/hig/B] missing-timeout  payments.py:7
      requests.post() waits forever by default.
  [MEDI/med/B] broad-wrap  payments.py:5
      All of charge is inside a broad try that doesn't re-raise.
[...]
```

<sub>Twenty lines written for this page, [shown in full in the examples](docs/examples.md#code-that-looks-finished). On a real 33,000-line billing app, a scan lead took an agent straight to a crash: two admin endpoints raised `NameError` on every call.</sub>

### Tests that pass and protect nothing

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

<sub>Written for this page and run with `occam mutate`.</sub>

There's more in [the examples](docs/examples.md), including a test-weakening edit caught in a real run, and the runs where occam didn't help.

## Using it

Skills load on their own when they're relevant, so mostly you just work as usual. To call one directly:

| | Plugin | Plain copy on Claude Code | Codex |
|---|---|---|---|
| Change or review code | `/occam:occam` | `/occam` | `$occam` |
| Audit or repair a codebase | `/occam:occam-audit` | `/occam-audit` | `$occam-audit` |
| Document code, with [human-voice](https://github.com/stephenoffer/human-voice) if it's installed | `/occam:occam-docs` | `/occam-docs` | `$occam-docs` |

Some prompts to start with:

```text
/occam:occam the total line says "1 items" when the count is one
/occam:occam report generation must finish in under 60s on 2M rows; find out why it doesn't and fix it
/occam:occam review this branch against main, don't change anything
/occam:occam-audit what's wrong with this cell? <paste>
/occam:occam-audit harden the billing service, ask me before changing the API
```

`occam-audit` is made for code that already exists, AI-generated code especially. It finds what's wrong, proves it, fixes what it's allowed to, and asks about the rest. Ask for an audit without asking for fixes and it stays read-only.

### The command line

Sixteen commands, standard-library Python 3.9 or later. They run the same under Claude Code, Codex or a bare terminal.

```bash
alias occam='python3 /path/to/occam/plugin/skills/occam/scripts/occam.py'

occam map      # size, strategy, risky files, how many agents to use
occam scan     # leads across 19 rule families
occam query    # plain answers: who calls this, what a change reaches, who owns it
occam mutate   # which behavior no test protects
occam gate     # critique your own change before calling it done
```

Big repositories are the point. On Django's 543,000 lines, most queries answer within 38 seconds. [Every command is documented here](docs/tools.md).

## Does it work?

It reliably changes how agents work. It hasn't yet made them pass more tests, and it costs more. The results come from paid head-to-head runs against the same agent with no skill, with the main comparisons preregistered, and the ones that didn't go occam's way are published too.

| | What we found |
|---|---|
| Agents work differently | Every enforcement mechanism in the evaluated version fired in real Claude Code runs, and the skill triggered correctly 22 of 22 times. Checking after the last edit went from 12 of 14 runs to 14 of 14. |
| Repairs are more careful | In two 28,000-line audit-and-repair tests, occam runs wrote regression tests in every run and added about a quarter as much code. In the latest, they made fewer unflagged behavior changes (6 against 20), treated fewer decoys as defects (2 against 10) and caused less new damage (10 items against 18). They also fixed fewer serious defects (median 48.5 of 60 against 55) and took about 1.8 times as long. |
| A promising lead | A blind model judge scored occam's finished code as simpler, with no difference on whether it would merge it. Human review is pending. |
| Pass rates aren't higher yet | Most cases were within reach of the agent alone: with no skill it passed 9 of 9 holdout runs, against 8 of 9 with occam on both Opus 5.5 and Sonnet 5.5. The Opus miss was a silent regression, in a run stopped at the time limit. On three hard cases occam passed 3 of 9 against 4 of 9, and the Python guidance showed no measured benefit. |
| It costs more | +57% on Opus and +85% on Sonnet on the holdout, with about twice the turns. The audit tests were the exception, at about 14% less. |

So the honest pitch is discipline: tests, reports that say what wasn't checked, fewer surprise changes, and a pause before anything irreversible. Whether that turns into higher pass rates on harder work is the question the next study asks, on eight new repositories. The full record is in [what was tested](docs/evidence.md).

## Other ways to install

**Guidance only:** copy `plugin/skills/*` into `~/.claude/skills/` for Claude Code, or `~/.agents/skills/` for [Codex](adapters/codex/README.md), which hasn't been run there yet. Check first that nothing there has the same name.

**Just the CLI:** nothing to install. Set the alias above and go.

## Good to know

- Occam is a safety net, not a security boundary. Rules that must never bend belong in deny rules, the sandbox and branch protection.
- Hooks can make a check run. They can't make it the right check, so that part is still the agent's job, and yours.
- If `python3` is missing or a hook errors, occam gets out of the way instead of wedging your session. Shell edits are detected best-effort.
- Python gets the deepest analysis. `occam query` traces imports and tests in Python, JavaScript and TypeScript, Go, Java and Kotlin, C and C++, Rust, Ruby and shell, while the scanner reads languages other than Python at text and brace level.
- Tested on macOS with Claude Code 2.1.318. Linux, Windows and Codex haven't been run yet.

## Docs

| Read | For |
|---|---|
| [Examples](docs/examples.md) | More real runs, and what good output looks like |
| [The `occam` CLI](docs/tools.md) | Every command, and how to read findings |
| [Claude Code integration](docs/claude-code.md) | Every hook, what it does and when it fires |
| [How agents get code wrong](docs/failure-modes.md) | Ten failure modes, and what occam does about each |
| [What was tested](docs/evidence.md) | Results, and the status of each combination |
| [All docs](docs/README.md) | Everything else, the repository layout and how to run the tests |

## License

[MIT](LICENSE)
